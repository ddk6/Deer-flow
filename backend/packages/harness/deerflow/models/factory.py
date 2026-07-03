import logging

from langchain.chat_models import BaseChatModel

from deerflow.config import get_app_config
from deerflow.reflection import resolve_class
from deerflow.tracing import build_tracing_callbacks

logger = logging.getLogger(__name__)


def _deep_merge_dicts(base: dict | None, override: dict) -> dict:
    """Recursively merge two dictionaries without mutating the inputs."""
    merged = dict(base or {})
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _vllm_disable_chat_template_kwargs(chat_template_kwargs: dict) -> dict:
    """Build the disable payload for vLLM/Qwen chat template kwargs."""
    disable_kwargs: dict[str, bool] = {}
    if "thinking" in chat_template_kwargs:
        disable_kwargs["thinking"] = False
    if "enable_thinking" in chat_template_kwargs:
        disable_kwargs["enable_thinking"] = False
    return disable_kwargs


def _enable_stream_usage_by_default(model_use_path: str, model_settings_from_config: dict) -> None:
    """Enable stream usage for OpenAI-compatible models unless explicitly configured.

    LangChain only auto-enables ``stream_usage`` for OpenAI models when no custom
    base URL or client is configured. DeerFlow frequently uses OpenAI-compatible
    gateways, so token usage tracking would otherwise stay empty and the
    TokenUsageMiddleware would have nothing to log.
    """
    if model_use_path != "langchain_openai:ChatOpenAI":
        return
    if "stream_usage" in model_settings_from_config:
        return
    if "base_url" in model_settings_from_config or "openai_api_base" in model_settings_from_config:
        model_settings_from_config["stream_usage"] = True


#这个是创建模型的函数
#这里面做了什么？ 这个和那个make_lead_agent是做的一件事吗？ 不是的 这是创建模型的函数 而make_lead_agent是创建agent的函数
#1获取配置 这个配置是从config.yaml中获取的
#2创建模型
#3创建工具
#4创建中间件
#5创建系统提示
#6创建状态模式

def create_chat_model(name: str | None = None, thinking_enabled: bool = False, **kwargs) -> BaseChatModel:
    """Create a chat model instance from the config.

    Args:
        name: The name of the model to create. If None, the first model in the config will be used.

    Returns:
        A chat model instance.
    """


    config = get_app_config() #app_config的实例  app_config是用来获取配置的 也就是说是先通过get_app_config函数获取app_config的实例 
    #然后通过app_config的实例获取配置 
    # 获取当前应用的配置对象 AppConfig。
    # 这个对象通常由 config.yaml 等配置源解析而来，
    # 后续通过它读取 models、tool_groups、model_config 等配置。
   
# 如果调用时没传模型名，就用配置里的第一个模型。
# 然后通过 name 找对应的模型配置。这里的 model_config 就是 config.yaml 中某个模型条目的 Python 对象。
    if name is None:
        name = config.models[0].name
    model_config = config.get_model_config(name)#这里获取的是model_config的实例
    if model_config is None:#如果model_config为空 就抛出异常
        raise ValueError(f"Model {name} not found in config") from None
    model_class = resolve_class(model_config.use, BaseChatModel)
    #resolve_class(...) 会动态 import 这个类，并确认它是 BaseChatModel 的子类。
    #所以 DeerFlow 不把模型写死。你换模型，主要改配置里的 use 和参数。
    model_settings_from_config = model_config.model_dump(#提取真正要传给模型构造函数的参数
#  这一步是把 model_config 转成 dict，但排除一些 DeerFlow 自己用的元信息。
# 比如这些不会传给模型类：
        exclude_none=True,
        exclude={
            "use",
            "name",
            "display_name",
            "description",
            "supports_thinking",
            "supports_reasoning_effort",
            "when_thinking_enabled",
            "when_thinking_disabled",
            "thinking",
            "supports_vision",
        },#因为它们是 DeerFlow 用来判断能力、展示 UI、选择模型类的，不是模型构造函数参数。
    )
    # Compute effective when_thinking_enabled by merging in the `thinking` shortcut field.
    # The `thinking` shortcut is equivalent to setting when_thinking_enabled["thinking"].
    has_thinking_settings = (model_config.when_thinking_enabled is not None) or (model_config.thinking is not None)#处理thinking 模式
    #配置里有没有声明“开启思考模式时要额外加什么参数”。
    effective_wte: dict = dict(model_config.when_thinking_enabled) if model_config.when_thinking_enabled else {}
    if model_config.thinking is not None:
        merged_thinking = {**(effective_wte.get("thinking") or {}), **model_config.thinking}
        effective_wte = {**effective_wte, "thinking": merged_thinking}
    #thinking_enabled 不是 DeerFlow 自己“想一想”的开关，而是会转换成具体模型 API 的参数。
    #只要配置中声明了参数  不管开不开启思考模式  都要将相应模式的参数合并到初始化参数中去

    # thinking_enabled=True 时，会把 when_thinking_enabled / thinking shortcut 转换后的参数合并到模型初始化参数中。
# thinking_enabled=False 时，则根据配置生成“禁用 thinking”的参数，比如 extra_body.thinking.type=disabled、
# vLLM chat_template_kwargs，或 native thinking={"type": "disabled"}。
    if thinking_enabled and has_thinking_settings:
        if not model_config.supports_thinking:
            raise ValueError(f"Model {name} does not support thinking. Set `supports_thinking` to true in the `config.yaml` to enable thinking.") from None
        if effective_wte:
            model_settings_from_config.update(effective_wte)

    if not thinking_enabled:
        if model_config.when_thinking_disabled is not None:
            # User-provided disable settings take full precedence
            model_settings_from_config.update(model_config.when_thinking_disabled)
        elif has_thinking_settings and effective_wte.get("extra_body", {}).get("thinking", {}).get("type"):
            # OpenAI-compatible gateway: thinking is nested under extra_body
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"thinking": {"type": "disabled"}},
            )
            model_settings_from_config["reasoning_effort"] = "minimal"
        elif has_thinking_settings and (disable_chat_template_kwargs := _vllm_disable_chat_template_kwargs(effective_wte.get("extra_body", {}).get("chat_template_kwargs") or {})):
            # vLLM uses chat template kwargs to switch thinking on/off.
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"chat_template_kwargs": disable_chat_template_kwargs},
            )
        elif has_thinking_settings and effective_wte.get("thinking", {}).get("type"):
            # Native langchain_anthropic: thinking is a direct constructor parameter
            model_settings_from_config["thinking"] = {"type": "disabled"}
    if not model_config.supports_reasoning_effort:
        kwargs.pop("reasoning_effort", None)
        model_settings_from_config.pop("reasoning_effort", None)#如果模型不支持 reasoning_effort，就删掉
        ##对普通模型，如果配置声明不支持 reasoning_effort，就从 kwargs 和配置参数里移除，避免传入模型不认识的参数。
        # 注意：CodexChatModel 后面有特殊分支，可能会重新设置 reasoning_effort。



    #OpenAI stream usage 兼容
    #这个是为了 token usage 统计。
    #如果模型是 langchain_openai:ChatOpenAI，而且配置了自定义 base_url，LangChain 默认可能不会统计流式 token usage。DeerFlow 这里自动补 stream_usage=True。
    _enable_stream_usage_by_default(model_config.use, model_settings_from_config)

    # For Codex Responses API models: map thinking mode to reasoning_effort
    from deerflow.models.openai_codex_provider import CodexChatModel

    #DeerFlow 针对 CodexChatModel 的特殊兼容处理。
    # 1. 去掉 Codex endpoint 不接受的参数
    # 2. 正确设置 Codex 的 reasoning_effort
    if issubclass(model_class, CodexChatModel):#如果当前要创建的模型类是 CodexChatModel 或它的子类，就进入特殊处理。
        # The ChatGPT Codex endpoint currently rejects max_tokens/max_output_tokens.
        model_settings_from_config.pop("max_tokens", None) #也就是 Codex endpoint 当前不接受 max_tokens / max_output_tokens 这类参数，所以这里先把 max_tokens 从配置里删掉，避免请求接口时报错。

        # Use explicit reasoning_effort from frontend if provided (low/medium/high)
        explicit_effort = kwargs.pop("reasoning_effort", None)#explicit_effort 代表用户/前端这次显式指定的推理强度。
        if not thinking_enabled:#如果没开 thinking，就设置成 none
            model_settings_from_config["reasoning_effort"] = "none"
        elif explicit_effort and explicit_effort in ("low", "medium", "high", "xhigh"):#如果前端显式传了合法 effort，就用前端的
            model_settings_from_config["reasoning_effort"] = explicit_effort
        elif "reasoning_effort" not in model_settings_from_config:#如果没有显式 effort，也没有配置，就默认 medium
            model_settings_from_config["reasoning_effort"] = "medium"

    # For MindIE models: enforce conservative retry defaults.
    # Timeout normalization is handled inside MindIEChatModel itself.
    #MindIE 特殊处理
    #如果是 MindIE 模型，默认把重试次数控制得保守一点，避免超时连环爆炸。
    if getattr(model_class, "__name__", "") == "MindIEChatModel":
        # Enforce max_retries constraint to prevent cascading timeouts.
        model_settings_from_config["max_retries"] = model_settings_from_config.get("max_retries", 1)
    #真正创建模型实例  kwargs 的优先级高于配置参数。    
    model_instance = model_class(**{**model_settings_from_config, **kwargs})

    callbacks = build_tracing_callbacks()#挂 tracing callback  
    #把 tracing 观察器装到模型实例上，让后续 LLM 调用能被记录和追踪。
    if callbacks: #如果配置了 LangSmith / Langfuse 之类追踪系统，就把 callback 挂到模型上。这样模型调用过程可以被记录下来。
        existing_callbacks = model_instance.callbacks or []
        model_instance.callbacks = [*existing_callbacks, *callbacks]
        logger.debug(f"Tracing attached to model '{name}' with providers={len(callbacks)}")
    return model_instance  #返回值是一个 LangChain 的 BaseChatModel 子类实例。
    #这个函数不是直接调用模型，而是根据 DeerFlow 配置创建一个可被 LangChain agent 使用的聊天模型对象。
    # 真正的模型调用发生在后续 create_agent 生成的 agent runtime 里。
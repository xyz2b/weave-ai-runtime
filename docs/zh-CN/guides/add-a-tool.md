# 添加 Tool

## 适合谁？

正在添加可复用执行能力的用户，例如文件检查、API 查询或结构化项目分析。

## 前置条件

- 一个由 starter 生成或以其他方式已经可运行的项目
- 一个 `.weavert/tools/` 目录
- 一项明显受益于结构化输入与输出的能力

## 文件型编写规则

支持的文件型路径是 `.weavert/tools/` 下的 Python 模块。
JSON 和 YAML 的 tool 定义文件不是这里默认支持的执行路径。

## 步骤

1. 创建 `.weavert/tools/check_file.py`
2. 导出一个具体的 `ToolDefinition`
3. 保持 schema 显式，行为聚焦
4. 给出符合真实行为的 traits 和 permission checks
5. 运行你的项目或某个聚焦 example，验证 tool contract

最小示例：

```python
from weavert import ToolDefinition, ToolTraits


def execute(tool_input, context):
    path = context.cwd / tool_input["file_name"]
    return {"exists": path.exists(), "path": str(path)}


TOOL_DEFINITION = ToolDefinition(
    name="check_file",
    description="Check whether a file exists under the current workspace.",
    input_schema={
        "type": "object",
        "properties": {"file_name": {"type": "string"}},
        "required": ["file_name"],
        "additionalProperties": False,
    },
    traits=ToolTraits(read_only=True, concurrency_safe=True),
    execute=execute,
)
```

## 值得优先使用的稳定字段

最重要的字段通常是：

- `name`
- `description`
- `input_schema`
- `traits`
- `validate_input`
- `check_permissions`
- `execute`

## 规范的 guarded-tool 模式

当一个 tool 需要更强的安全约束时，常见组合是：

1. `validate_input`
   - 尽早拒绝格式错误或不完整的请求
2. `check_permissions`
   - 让 runtime 或 host 的 permission 路径显式参与
3. 准确的 `traits`
   - 诚实标记只读、破坏性或并发敏感行为

这是把 tool 嵌入更大工作流前最值得先做的一步。

## 面向 live OpenAI route 的 schema 指南

如果该 tool 可能会走内置 OpenAI 路线，请记住：

- 优先使用显式 object schema
- 优先为数组项提供显式 schema
- 除非确有需要，否则尽量关闭 `additionalProperties`
- 对内置 strict-tool export 路径，避免依赖 schema-valued `additionalProperties`

传输层可能会为兼容严格 provider 而规范化可选字段，但在 runtime 层的编写模型里，你仍应保持 schema 明确且足够小。

## 预期结果

Runtime 能从 `.weavert/tools/` 发现你的 tool，把它暴露给合格的 agents，并在执行前完成输入验证。

## 下一步

运行 `python3 -B -m examples.tools.file_backed_tool_demo` 或 `python3 -B -m examples.tools.guarded_tool_demo`，隔离验证这个 seam。

## 另见

- `../concepts/tools-agents-skills.md`
- `../guides/testing-and-observability.md`
- `../deep-dives/weavert-definition-authoring-guide.md`

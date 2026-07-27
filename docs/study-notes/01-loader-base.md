# File: core/loader/base.py

## 作用

定义了整个 RAG 系统的数据单元 `Document` 和加载器接口 `BaseLoader`。所有加载器（PDF/Text/Code）都必须实现这个接口。

## 完整代码（逐行讲解）

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
```

- `abc` 模块：Python 的抽象类机制，等价于 Java 的 `abstract class` 和 `abstract method`。
- `dataclass`：Python 3.7+ 引入，自动生成 `__init__`、`__repr__`、`__eq__` 等方法。等价于 Java 的 `record` 或 Lombok 的 `@Data`。
- `field`：dataclass 中定义字段默认值的工具函数。

```python
@dataclass
class Document:
    content: str
    metadata: dict = field(default_factory=dict)
```

- `@dataclass` 装饰器：自动生成构造方法。有了它，`Document(content="hello")` 会自动创建实例。
- `content: str` — 文档的文本内容。
- `metadata: dict = field(default_factory=dict)` — 元数据字典（来源、页码、类型等）。
- `default_factory=dict` 和 `={}` 的区别：Python 的默认参数在函数定义时求值一次。如果用 `={}`，所有实例共享同一个空字典，导致修改一个实例的 metadata 会影响其他实例。`default_factory=dict` 在每次创建实例时调用 `dict()` 生成一个新的空字典，避免了这个问题。

> **Java 对比：** Python dataclass 等价于 Java record：
> ```java
> public record Document(String content, Map<String, String> metadata) {
>     public Document(String content) {
>         this(content, new HashMap<>());
>     }
> }
> ```

```python
class BaseLoader(ABC):
    """文档加载器抽象接口，所有加载器需实现 load 方法"""

    @abstractmethod
    def load(self, source: str) -> List[Document]:
        ...
```

- `BaseLoader(ABC)` — 继承 ABC（Abstract Base Class），等价于 Java 的 `abstract class BaseLoader`。
- `@abstractmethod` — 子类必须实现该方法。如果子类没实现，实例化时会抛出 `TypeError`。
- `def load(self, source: str) -> List[Document]` — 接口方法。接收文件路径，返回文档列表。
- `...` — Ellipsis 字面量，作为占位符。等价于 Java 的 `;` 或 `// TODO`。

## 重点总结

1. **Document 是整个系统的数据核心** — 所有模块（Loader、Chunker、Retriever、Generator）都通过 Document 传递数据。
2. **`default_factory` 陷阱** — 永远不要在 dataclass 中用 `={}` 作为默认值，必须用 `field(default_factory=dict)`。
3. **接口设计的核心原则** — 输入是 `source: str`，输出是 `List[Document]`。所有加载器都遵循这个契约，上层代码不需要关心具体加载器。

## 大厂面试可能问

- **Q: 为什么用 dataclass 而不是普通 class？** — 减少样板代码。dataclass 自动生成 `__init__`、`__repr__`、`__eq__`，开发者只需要声明字段。

- **Q: `field(default_factory=dict)` 和 `metadata: dict = {}` 有什么区别？** — 后者在类定义时创建一次空字典，所有实例共享同一个引用。修改一个实例的 metadata 会影响其他实例。前者每次创建实例时调用 `dict()` 生成新的空字典，是安全的。

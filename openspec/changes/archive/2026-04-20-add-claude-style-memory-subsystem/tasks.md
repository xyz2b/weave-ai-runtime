## 1. Memory Manager Foundations

- [x] 1.1 新增 memory models、provider boundary、`MemoryManager` 与默认文件型 provider
- [x] 1.2 实现 memory path resolution、`MEMORY.md` 入口加载与 `user/project/local` scope 解析

## 2. Memory Retrieval and Extraction

- [x] 2.1 实现 pre-turn relevant memory retrieval，并将 retrieval 结果接入上下文装配
- [x] 2.2 实现主线程 post-turn memory extraction、持久化与通知/记录路径

## 3. Scope Safety

- [x] 3.1 实现 memory 目录读写边界与与普通工作目录的隔离保护
- [x] 3.2 将 agent memory scope 配置接入 session startup 与 delegated execution context

## 4. Verification

- [x] 4.1 增加测试，覆盖 `MEMORY.md` 入口加载、memory scopes、retrieval/extraction 与 path-boundary 行为
- [x] 4.2 增加 Claude 风格 memory fixtures，锁定默认语义而不是通用 KV 行为

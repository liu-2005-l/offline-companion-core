# Verification Reference

## Iron Law
**禁止**标记任务完成，除非提供最新运行结果作为证据。
**必须**在声明完成前执行验证并附实际输出。

## Reasoning
“写了代码 ≠ 跑通了”——这条对 AI 工具成立，对人一样成立。
没有运行结果证据的“已完成”声明，视为破坏规则精神。
这是 AI 编码助手最常见的自欺模式。

## Procedure

### UI 改动
1. 等待页面完全加载（无 spinner）
2. 截图（长页面分 3-5 段，每段约 800px）
3. 自查：内容加载？展示具体改动？无视觉 bug？
4. 每段标注：“Hero”、“Features”、“Footer”等

### API / 逻辑改动
1. 运行测试或调用 API
2. 展示实际输出：

```text
GET /api/users -> {"id": 1, "name": "test"}
```

3. 不只是“it works”——展示真实响应

### 测试套件
1. 运行完整测试套件（`pytest` 或项目等价命令）
2. 输出实际 pass/fail 计数：

```text
468 passed, 3 skipped
```

3. 如有 failure → 修复 → 重新运行 → 直到全绿
4. skip 不算 failure，但需在报告中列出 skip 原因
5. 将最终测试输出作为阶段完成证据附入 `skill_advance_stage(action=complete, evidence=...)`

### Reviewer 输出协议
1. `code-reviewer` 必须返回结构化 JSON：

```json
{"approved": false, "issues": ["具体问题"], "suggestions": ["具体建议"]}
```

2. `approved=false` 时，不得标记阶段完成。
3. `issues[]` 必须列出阻断问题；没有问题时返回空数组。
4. `suggestions[]` 仅放非阻断改进建议，不得混入阻断项。
5. reviewer 输出解析失败时按 `approved=false` 处理，并要求重新审查。

### 禁止项
- **禁止**仅凭“代码看起来正确”声明完成
- **禁止**用“应该没问题”替代运行结果
- **禁止**跳过测试套件直接标记完成
- **禁止**在测试未全绿时标记完成
- **禁止**用“我写了测试”替代“我运行了测试”——写了 ≠ 跑了

### 修复循环
如果截图或输出显示问题：
1. 修复代码
2. 重新部署或运行
3. 生成新截图或输出
4. 仍有问题 → 回到 1
5. 修复后 → 才可发送

**禁止**发送“I noticed X is wrong, will fix”——先修复再发送。

### 多状态流
按顺序标注：1/4: Form → 2/4: Loading → 3/4: Error → 4/4: Success

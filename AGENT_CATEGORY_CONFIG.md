# IBM Orchestrate Agent Category 配置指南

## 📋 配置目标

让 Agent 自动分析用户问题，确定 Category，并在创建票据时传递给后端，实现智能分组。

---

## Step 1: 配置 Response Object (你正在做的)

### Category 字段设置：

根据你的截图，在 **Edit an object output** 界面：

**Name (字段名):**
```
Category
```

**Type:**
- ✅ **String** (不要选 "List of strings")

**Description (描述):**
```
AI-determined issue category for intelligent ticket grouping. Be descriptive and specific (e.g., 'VPN Access', 'Laptop Hardware', 'Azure Permissions').
```

**Set default value (可选):**
- 关闭（不设默认值，让 AI 决定）

**完整的 Response Object 应该包含:**
- `ai_draft` (string) - **技术总结**：供管理员看的内部研究结果或总结。
- `admin_draft` (string) - **回复草稿**：以管理员口吻写的、准备发给用户的正式回复。
- `Category` (string) - **大类** (Network, Hardware, Software, Account, Facility, Security)
- `Subcategory` (string) - **细分** AI 思考的具体领域 (例如: VPN Error, Slack Permissions)

---

## Step 2: 配置 Agent Instructions (核心)

在 Agent 的 **Instructions** 或 **Prompt** 配置中，添加以下逻辑：

## Agent Prompt Configuration

### A. System Key / System Prompt
*Set this in the "System Instructions" block.*

```markdown
# Role
You are LoopBack AI, an expert IT Support Assistant. Your goal is to analyze user queries, search the knowledge base, and determine the best resolution.

# Workflow Logic

## 1. Analyze and Score (Internal)
Evaluate the Search Results against the User Query to determine your confidence:
1.  **HIGH (80-100%)**: Exact match found. Output the solution directly.
2.  **MEDIUM (60-79%)**: Relevant guides found (e.g., VPN steps/Printer reset). Derive a helpful answer from the content.
3.  **LOW (<60%)**: No relevant info found. You must escalate to a human agent.

## 2. Categorization Rules
Classify the issue into exactly ONE Category and ONE Subcategory:
-   **Category**: Must be one of [`Network`, `Hardware`, `Software`, `Account`, `Facility`, `Security`].
-   **Subcategory**: Specific 1-2 word topic (e.g., "VPN Error", "Azure Login", "Laptop Screen").

## 3. Drafting Guidelines

### A. ai_draft (Technical Summary for Admin)
-   Write a concise, technical summary of the issue and your findings.
-   *Example:* "User reports printer jam. KB found model X1 guide. Provided reset steps."

### B. admin_draft (Response to User)
-   This is the **final message** the user will see.
-   **Tone**: Empathetic, Professional, Action-Oriented.
-   **If Score > 60 (Solvable)**: Provide the clear, step-by-step solution based on the Search Results. Do NOT create a ticket just to say "I don't know" if the info is there.
-   **If Score < 60 (Unsolvable)**: State that you are creating a ticket for the human team. (e.g., "I've logged a ticket regarding your issue. Our team will contact you shortly.").
-   **Constraint**: NEVER ask the user to input the same info again.

# Output Format
Return a JSON object:
{
  "Category": "string",
  "Subcategory": "string",
  "ai_draft": "string",
  "admin_draft": "string"
}
```

### B. User Prompt
*This is the actual input sent to the model.*

```text
Input Data:
- User Query: "{{user_query}}"
- Knowledge Base Search Results: "{self.input.Search_result}"

Task:
Analyze the above data and generate the JSON response defined in the System Instructions.
```

---

## Step 3: 修改 Skill 调用逻辑

在 Agent 的 workflow 中，调用 `lucas_2: Create a new support ticket` 时：

### Before (旧方式):
```json
{
  "query": "User's issue description",
  "ai_draft": "AI analysis"
}
```

### After (新方式 - 包含 category):
```json
{
  "category": "{{Category}}",  // 从 Agent 输出获取
  "subcategory": "{{Subcategory}}",       // Include subcategory if using it
  "query": "{{user_query}}",
  "ai_draft": "{{ai_draft}}",
  "admin_draft": "{{admin_draft}}"
}
```

**使用变量映射:**
- Agent 输出的 `Category` → Skill 参数的 `category`
- Agent 输出的 `Subcategory` → Skill 参数的 `subcategory`
- Agent 分析的摘要 → Skill 参数的 `ai_draft`
- Agent 生成的回复 → Skill 参数的 `admin_draft`

---

## Step 4: 测试配置

### Test Case 1: Network Issue
**User Input:**
```
"The VPN won't connect"
```

**Expected Agent Output:**
```json
{
  "ai_draft": "User reports VPN connection failure. Checking knowledge base for VPN troubleshooting steps...",
  "Category": "Network"
}
```

**Expected Backend Behavior:**
- Creates ticket TKT-XXXX
- Searches for existing "Network" category tickets
- If found similar VPN issue → Groups together
- If new → Creates new group

### Test Case 2: Hardware Issue
**User Input:**
```
"Printer is offline"
```

**Expected:**
- Category: "Hardware"
- Groups with other printer issues

### Test Case 3: Multiple Similar Issues
**Scenario:** 3 users report Wi-Fi problems

```
User 1: "Wi-Fi not working"          → Category: Network, TKT-1001, group_id: TKT-1001
User 2: "Internet keeps dropping"    → Category: Network, TKT-1002, group_id: TKT-1001 ✅
User 3: "Can't connect to wireless"  → Category: Network, TKT-1003, group_id: TKT-1001 ✅
```

**Admin sees:** 1 group with 3 tickets → Click "Broadcast Fix" → All resolved! 🎉

---

## Step 5: 验证分类准确性

**Good Category Assignment:**
- ✅ "VPN error" → Network
- ✅ "Screen cracked" → Hardware
- ✅ "Can't install app" → Software
- ✅ "Password expired" → Account
- ✅ "Meeting room projector broken" → Facility

**Edge Cases:**
- "Computer slow" → Hardware (hardware performance issue)
- "Browser crashes" → Software (application issue)
- "Can't access shared drive" → Network (network access)
- "MFA not working" → Account (authentication)

---

## 🎯 预期效果

### Before (无 Category):
```
TKT-1001: "wifi broken" (group_id: TKT-1001)
TKT-1002: "internet not working" (group_id: TKT-1002) ❌ 分开
TKT-1003: "wireless issue" (group_id: TKT-1003) ❌ 分开
```
**问题:** 3个相似问题 = 3个独立票据

### After (有 Category):
```
TKT-1001: "wifi broken" (category: Network, group_id: TKT-1001)
TKT-1002: "internet not working" (category: Network, group_id: TKT-1001) ✅ 分组
TKT-1003: "wireless issue" (category: Network, group_id: TKT-1001) ✅ 分组
```
**效果:** 3个相似问题 = 1个组，管理员一次解决！

---

## 🚀 配置完成后

1. **保存 Agent 配置**
2. **重新发布 Agent**
3. **测试不同类型问题:**
   - Network: "VPN won't connect"
   - Hardware: "Printer offline"
   - Software: "Can't install Slack"
   - Account: "Password reset"
   - Facility: "Meeting room tech issue"

4. **检查后端日志:**
```bash
tail -f /tmp/server_log.txt | grep category
```

应该看到:
```
DEBUG: 📂 Ticket has category: Network
DEBUG: 🔗 Category match! Grouped with TKT-1001 (category: Network, similarity: 60%)
```

---

## 📝 Quick Checklist

- [ ] Response Object 添加 `Category` 字段 (String)
- [ ] Agent Instructions 包含分类规则
- [ ] Agent 输出格式包含 Category
- [ ] Skill 调用传递 category 参数
- [ ] 测试 5 种不同类别的问题
- [ ] 验证相似票据成功分组

**完成这些后，你的票据分组系统将完全自动化！** ✅

---

## Step 4: [OPTIONAL] Simplified Workflow (No Branching)

**User Request**: "Can I just use one node instead of complex branches?"
**Answer**: YES! This is known as "Agentic Tool Use".

### How to set it up:
1.  **Delete the Decision Diamond** (The "Confidence Check" branch).
2.  Have just **ONE "Generative Response" node**.
3.  In that node's settings:
    *   **Prompt**: Use the "System Prompt" from Step 2.
    *   **Tools (Actions)**: Enable `Create a new support ticket`.
    *   **Logic**: The AI (LLM) will now deciding *reading your Prompt rules*:
        *   "If score < 60 -> call tool."
        *   "If score > 60 -> just reply."

This forces the AI to be the "Brain" and prevents the "Double Ticket" bug where both the flow logic AND the AI try to create a ticket simultaneously.

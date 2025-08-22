# BrowserFairy 🧚 - 让AI看见你的浏览器

[English](./docs/en/README.md) | 简体中文

## 📚 文档导航

- 🚀 [快速开始指南](./docs/zh-CN/getting-started.md) - 详细安装和配置
- 🤖 [AI辅助调试](./docs/zh-CN/ai-debugging.md) - Claude Code/Cursor集成最佳实践
- 🧠 [AI智能分析指南](./docs/AI_ANALYSIS_GUIDE.md) - Claude AI性能分析配置和使用
- 📊 [数据分析指南](./docs/zh-CN/data-analysis.md) - 理解监控数据格式
- ⚡ [功能特性](./docs/zh-CN/features.md) - 完整功能列表
- 🔧 [命令参考](./docs/zh-CN/commands.md) - 所有命令详解
- 🏗️ [技术架构](./docs/zh-CN/architecture.md) - 深入技术实现

---

**一句话介绍**：BrowserFairy让Claude Code/Cursor等AI编程助手能够"看见"浏览器里发生的一切，将调试从"盲猜"变为"精准定位"。

## 🎯 解决什么问题？

### 你是否遇到过这样的对话？

```
你："页面点击按钮没反应"
Claude Code："试试添加console.log看看..."
你："还是不行"
Claude Code："可能是事件绑定问题，检查一下..."
（20分钟后还在猜测...）
```

### 使用BrowserFairy后

```
你："页面点击按钮没反应"
Claude Code："我看到了TypeError在Button.jsx第45行，是因为state.user为null，这里需要加个空值检查"
（2分钟修复完成）
```

## 🚀 30秒快速体验

```bash
# 安装（需要Python 3.11+）
curl -sSL https://raw.githubusercontent.com/shanrichard/browserfairy/main/install.sh | sh

# 一键启动监控（推荐：保存所有脚本源代码）
browserfairy --start-monitoring --enable-source-map --persist-all-source-maps

# 让AI只看错误信息（调试模式）
browserfairy --start-monitoring --enable-source-map --persist-all-source-maps --output errors-only --data-dir .

# 🆕 AI智能分析（需配置API Key）
export ANTHROPIC_API_KEY="your-key-here"
browserfairy --analyze-with-ai --focus memory_leak
```

就这么简单！BrowserFairy会：
- ✅ 自动启动独立Chrome实例
- ✅ 实时监控所有错误和异常
- ✅ 保存数据到当前目录供AI读取
- ✅ Chrome关闭时自动停止

## 💡 核心使用场景

### 场景1：精准定位错误
**之前**：通过描述猜测问题 → **现在**：AI直接看到错误堆栈和行号

### 场景2：内存泄漏排查  
**之前**：不知道哪里在泄漏 → **现在**：精确定位到ProductList.jsx:156的事件监听器未清理，或者DataProcessor.js:89的allocateArray()函数分配了50MB内存但未释放

### 场景3：性能优化
**之前**：页面卡但不知道原因 → **现在**：发现5.2MB的API响应和156ms的长任务阻塞

## 📦 安装

### 方式1：快速安装（推荐）
```bash
curl -sSL https://raw.githubusercontent.com/shanrichard/browserfairy/main/install.sh | sh
```

### 方式2：手动安装
```bash
# 安装uv包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆并安装
git clone https://github.com/shanrichard/browserfairy.git
cd browserfairy
uv sync
uv run pip install -e .
```

## 🎮 常用命令

```bash
# 推荐：完整监控模式（保存所有脚本源代码）
browserfairy --start-monitoring --enable-source-map --persist-all-source-maps

# AI调试模式（保存到当前目录）
browserfairy --start-monitoring --enable-source-map --persist-all-source-maps --data-dir .

# 后台持续监控
browserfairy --start-monitoring --enable-source-map --persist-all-source-maps --daemon

# 分析已收集的数据
browserfairy --analyze-sites

# 更多命令
browserfairy --help
```

## 📊 输出数据说明

监控数据保存为JSONL格式，AI可以直接读取：

```
./bf_data/                          # 指定的数据目录
└── session_2025-01-20_143022/     # 监控会话
    └── example.com/                # 按网站分组
        ├── console.jsonl           # 错误和日志
        ├── network.jsonl           # 网络请求
        ├── memory.jsonl            # 内存数据
        ├── gc.jsonl                # 垃圾回收事件
        ├── longtask.jsonl          # 长任务检测
        ├── heap_sampling.jsonl     # 内存分配采样分析
        ├── source_maps/            # Source Map文件（如果存在）
        └── sources/                # 脚本源代码（--persist-all-source-maps时保存所有JS文件）
```

## 🧠 AI智能分析（新功能）

BrowserFairy现在集成了Claude AI，可以智能分析收集的监控数据：

### 快速开始
```bash
# 1. 获取API Key（访问 https://console.anthropic.com）
export ANTHROPIC_API_KEY="sk-ant-api03-xxx..."

# 2. 运行AI分析
browserfairy --analyze-with-ai                    # 综合分析
browserfairy --analyze-with-ai --focus memory_leak # 内存泄漏专项
browserfairy --analyze-with-ai --focus performance # 性能瓶颈分析
```

### 分析能力
- **内存泄漏定位**：精确到源代码行级别，识别未清理的事件监听器、闭包引用等
- **性能瓶颈诊断**：分析长任务、GC频率、主线程阻塞
- **错误根因分析**：结合Source Maps定位真实代码位置
- **网络优化建议**：API响应时间分析、失败率统计、优化建议
- **自动生成报告**：分析结果保存为Markdown文件（`ai_analysis_[focus]_[timestamp].md`）

详细配置和使用说明请查看 [AI智能分析指南](./docs/AI_ANALYSIS_GUIDE.md)

## 🌟 与其他工具的协同

BrowserFairy专注于**运行时性能监控**，与测试工具形成完美互补：

### 开发工具链中的定位

```
编写代码（Cursor/Claude Code） → 测试（Playwright/Cypress） → 部署 → 监控（BrowserFairy）
                                                                  ↓
                                                          发现问题 → AI分析 → 修复
```

### 独特价值

| 工具类型 | 代表工具 | 主要用途 | BrowserFairy的互补价值 |
|---------|---------|---------|----------------------|
| **浏览器自动化** | Playwright MCP | AI控制浏览器 | 我们**监听**浏览器实际发生了什么 |
| **E2E测试** | Cypress | 功能验证 | 我们诊断**为什么**测试失败或变慢 |
| **单元测试** | Vitest | 组件测试 | 我们提供**生产环境**的真实数据 |

### 协同示例

```javascript
// Cypress告诉你：测试失败了
cy.get('.button').click()  // ❌ 按钮没响应

// BrowserFairy告诉你：为什么失败了
{
  "jsHeapSize": "850MB",     // 内存泄漏
  "longTask": "5600ms",      // 主线程阻塞
  "listeners": 1500          // 事件监听器泄漏
}
```

💡 **核心差异**：其他工具关注"应该发生什么"，BrowserFairy展示"实际发生了什么"

## 🤝 贡献

欢迎提交Issue和PR！查看[贡献指南](CONTRIBUTING.md)了解更多。

## 📄 许可证

[MIT License](LICENSE)

---

**让AI真正看见你的浏览器** - BrowserFairy 🧚
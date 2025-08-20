# BrowserFairy 🧚 - 让AI看见你的浏览器

[English](./docs/en/README.md) | 简体中文

## 📚 文档导航

- 🚀 [快速开始指南](./docs/zh-CN/getting-started.md) - 详细安装和配置
- 🤖 [AI辅助调试](./docs/zh-CN/ai-debugging.md) - Claude Code/Cursor集成最佳实践
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

# 一键启动监控（自动启动Chrome）
browserfairy --start-monitoring

# 让AI只看错误信息（推荐）
browserfairy --start-monitoring --output errors-only --data-dir .
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
# AI调试模式（推荐）
browserfairy --start-monitoring --output errors-only --data-dir .

# 后台持续监控
browserfairy --start-monitoring --daemon

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
        └── heap_sampling.jsonl     # 内存分配采样分析 🆕
```

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
# AI辅助调试完全指南

## 从"盲调试"到"精准定位"

想象一下，你和Claude Code在协作调试，但Claude Code看不见浏览器——就像两个人通过电话描述一幅画。BrowserFairy改变了这一切。

## 🎯 快速开始

### 1. 在项目目录启动监控

```bash
# 启用Source Map解析（让AI看到源代码位置）并将监控文件写到当前项目所在的文件夹
browserfairy --start-monitoring --enable-source-map --data-dir ./debug_data

# 或者收集完整性能数据（包含Source Map）
browserfairy --start-monitoring --output performance --enable-source-map --data-dir ./debug_data
```

> 💡 **重要提示**：`--enable-source-map` 参数让BrowserFairy自动解析压缩代码的Source Map，将错误定位到原始源代码位置。这对AI调试至关重要！

### 2. 复现问题

正常使用你的Web应用，BrowserFairy会自动捕获：
- JavaScript错误和异常
- 网络请求失败
- 内存泄漏征兆
- 性能瓶颈

### 3. 让AI分析数据

```
你：Claude Code，我点击提交按钮没反应，debug_data目录有监控数据
Claude Code：让我看看...发现了问题！在console.jsonl中有个TypeError:
  
  原始错误位置（压缩代码）：
  - 文件：bundle.min.js:1:45678
  
  通过Source Map解析后的真实位置：
  - 文件：src/components/SubmitButton.jsx:45
  - 函数：handleSubmit
  - 错误：Cannot read property 'value' of null
  - 源代码：const username = form.username.value; // 这行出错了
  
解决方案：在访问前添加空值检查...
```

> 🎯 **Source Map的威力**：没有Source Map，AI只能看到`bundle.min.js:1:45678`这种无意义的位置。有了Source Map，AI能精确定位到`SubmitButton.jsx:45`的`handleSubmit`函数！

## 🔥 实际案例

### 案例1：React组件内存泄漏

**场景**：电商网站商品列表页面使用30分钟后变卡

**传统调试对话**：
```
你：页面用久了会变卡
Claude Code：可能是内存泄漏，检查是否有：
- 未清理的定时器
- 未解绑的事件监听器
- 循环引用
（一个个排查，耗时2小时）
```

**使用BrowserFairy后**：
```
你：页面变卡了，我用BrowserFairy监控了30分钟
Claude Code：我看到memory.jsonl中的数据：
- JS堆从25MB增长到350MB
- 事件监听器从50个增长到1500个
- 具体泄漏源：ProductList.jsx:156的handleProductClick
  绑定到了15个元素但从未解绑
  
问题代码：
useEffect(() => {
  elements.forEach(el => el.addEventListener('click', handleClick))
  // 缺少cleanup
})

修复方案：添加cleanup函数...
```

### 案例2：API性能问题

**场景**：仪表盘加载缓慢

**使用BrowserFairy后，Claude Code能看到**：
```json
// network.jsonl
{
  "type": "network_request_complete",
  "url": "https://api.example.com/dashboard/data",
  "duration": 5.2,
  "encodedDataLength": 5242880,
  "detailedStack": {
    "reason": "large_download",
    "frames": [
      {
        "functionName": "Dashboard.fetchAllData",
        "url": "https://app.js",
        "lineNumber": 89
      }
    ]
  }
}
```

**Claude Code的分析**：
> 我看到Dashboard.fetchAllData在第89行发起了5.2MB的请求，耗时5.2秒。建议：
> 1. 实现分页加载
> 2. 只请求可见数据
> 3. 添加缓存机制

### 案例3：第三方脚本影响

**场景**：页面间歇性卡顿

**BrowserFairy捕获的长任务数据**：
```json
// longtask.jsonl
{
  "type": "longtask",
  "duration": 156.7,
  "attribution": [
    {
      "containerType": "iframe",
      "containerName": "ads-frame",
      "containerSrc": "https://ads.provider.com/widget.html"
    }
  ]
}
```

**Claude Code的建议**：
> 广告脚本导致156ms的主线程阻塞。建议延迟加载广告或使用Web Worker隔离。

## 📊 输出模式选择

### 根据调试需求选择合适的数据

| 模式 | 命令参数 | 适用场景 | 数据量 |
|------|---------|----------|---------|
| 仅错误 | `--output errors-only` | 快速调试错误 | 最小 |
| AI调试 | `--output ai-debug` | AI辅助综合调试 | 适中 |
| 性能分析 | `--output performance` | 性能优化 | 较大 |
| 完整数据 | `--output all` | 深度分析 | 最大 |

### 自定义输出

```bash
# 只要控制台错误和网络失败
browserfairy --start-monitoring \
  --output console:error,network:failed \
  --data-dir ./debug
```

## 🤖 与不同AI工具集成

### Claude Code(推荐)

1. 将数据目录设置在项目内：`--data-dir ./debug_data`
2. 告诉Claude Code数据位置
3. Claude Code会自动分析JSONL文件

### Cursor

1. 在项目根目录启动监控
2. Cursor的AI会自动识别新增的调试数据
3. 使用Cursor的Chat功能询问问题

### GitHub Copilot

1. 在代码注释中引用数据
2. Copilot会参考数据生成修复建议

## 💡 最佳实践

### 1. 项目集成

在 `package.json` 添加脚本：
```json
{
  "scripts": {
    "debug:start": "browserfairy --start-monitoring --output errors-only --data-dir ./debug_data",
    "debug:analyze": "browserfairy --analyze-sites"
  }
}
```

### 2. 调试工作流

```bash
# 步骤1：启动监控
npm run debug:start

# 步骤2：复现问题
# （在浏览器中操作）

# 步骤3：让AI分析
# "Claude Code，请分析 ./debug_data 中的错误"

# 步骤4：应用修复
# （根据AI建议修改代码）
```

### 3. 数据管理

```bash
# 调试完成后清理数据
rm -rf ./debug_data

# 或者归档供后续分析
tar -czf debug_session_$(date +%Y%m%d).tar.gz ./debug_data
```

## 🚀 进阶技巧

### 1. 监控特定网站

```bash
# 使用Chrome打开特定页面后启动
browserfairy --monitor-comprehensive \
  --output errors-only \
  --data-dir ./debug
```

### 2. 长期监控

```bash
# 后台持续监控，定期让AI分析趋势
browserfairy --start-monitoring --daemon
```

### 3. 对比分析

保存多个会话的数据，让AI对比：
- 修复前 vs 修复后
- 开发环境 vs 生产环境
- 不同用户的使用模式

## 📚 深入了解

- [数据格式详解](./data-analysis.md) - 理解每个字段的含义
- [常见问题诊断](./troubleshooting.md) - 典型问题解决方案
- [命令参考](./commands.md) - 完整命令列表

---

**记住**：BrowserFairy不是要取代你的调试技能，而是让AI成为你的"眼睛"，一起更高效地解决问题。
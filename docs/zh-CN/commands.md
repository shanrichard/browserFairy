# 命令参考手册

## 概述

BrowserFairy提供了丰富的命令行选项，支持不同的监控场景。

## 基础命令

### 一键启动

```bash
browserfairy --start-monitoring [选项]
```

自动启动Chrome实例并开始监控。

**选项**：
- `--daemon` - 后台运行
- `--duration <秒>` - 监控持续时间
- `--output <模式>` - 输出过滤（见下文）
- `--data-dir <路径>` - 数据保存目录
- `--enable-source-map` - 启用Source Map解析（将压缩代码错误映射到源代码）

**示例**：
```bash
# 监控5分钟
browserfairy --start-monitoring --duration 300

# 后台运行
browserfairy --start-monitoring --daemon

# AI调试模式（推荐启用Source Map）
browserfairy --start-monitoring --output errors-only --enable-source-map --data-dir .
```

### 手动连接监控

```bash
browserfairy --monitor-comprehensive [选项]
```

连接到已运行的Chrome实例（需要先启动Chrome调试模式）。

**Chrome启动方式**：
```bash
# macOS
open -a "Google Chrome" --args --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222

# Windows
chrome.exe --remote-debugging-port=9222
```

## 输出控制

### 输出模式 (--output)

控制收集哪些类型的数据：

| 模式 | 说明 | 包含数据 |
|------|------|----------|
| `all` | 完整数据（默认） | 所有类型 |
| `errors-only` | 仅错误 | console:error, exception, network:failed |
| `ai-debug` | AI调试 | errors + memory |
| `performance` | 性能分析 | memory, gc, network:complete |
| `minimal` | 最小化 | console:error, exception |

### 自定义输出

```bash
# 细粒度控制
browserfairy --monitor-comprehensive \
  --output console:error,console:warn,network:failed,memory

# 支持的类型：
# - console:error/warn/log/info/debug
# - network:start/complete/failed
# - memory, gc, exception, longtask, storage
```

### 数据目录 (--data-dir)

指定数据保存位置：

```bash
# 保存到当前目录
browserfairy --monitor-comprehensive --data-dir .

# 保存到指定路径
browserfairy --monitor-comprehensive --data-dir /path/to/data

# 使用环境变量
export BROWSERFAIRY_DATA_DIR=/my/data
browserfairy --monitor-comprehensive
```

## 专项监控

### 内存监控

```bash
browserfairy --monitor-memory
```

仅监控内存使用情况。

### 标签页监控

```bash
browserfairy --monitor-tabs
```

实时监控标签页的创建、关闭和URL变化。

### 基础数据收集

```bash
browserfairy --start-data-collection
```

启动基础的数据收集（内存+存储）。

## 数据分析

### 基础统计分析

```bash
browserfairy --analyze-sites [hostname]
```

分析收集的监控数据，提供基础统计信息。

输出示例：
```
BrowserFairy 数据分析概览
==================================================
发现监控会话: 3 个

example.com:
  监控会话: 2 个
  总记录数: 1247
  数据类型: console, memory, network

news.site.com:
  监控会话: 1 个
  总记录数: 892
  数据类型: console, memory
```

### 分析特定网站

```bash
browserfairy --analyze-sites example.com
```

显示特定网站的详细分析。

### AI智能分析（新功能）

```bash
browserfairy --analyze-with-ai [session_dir] [选项]
```

使用Claude AI深度分析监控数据，提供智能诊断和优化建议。

**前置要求**：
```bash
# 配置API Key（访问 https://console.anthropic.com 获取）
export ANTHROPIC_API_KEY="sk-ant-api03-xxx..."
```

**选项**：
- `--focus <类型>` - 分析焦点
  - `general` - 综合分析（默认）
  - `memory_leak` - 内存泄漏专项
  - `performance` - 性能瓶颈分析
  - `network` - 网络优化
  - `errors` - 错误诊断
- `--custom-prompt <文本>` - 自定义分析需求

**示例**：
```bash
# 综合分析最新session
browserfairy --analyze-with-ai

# 内存泄漏专项分析
browserfairy --analyze-with-ai --focus memory_leak

# 自定义分析需求
browserfairy --analyze-with-ai --custom-prompt "分析最近1小时的错误"
```

详细配置和使用说明请查看 [AI智能分析指南](../AI_ANALYSIS_GUIDE.md)

## 存储快照

### DOMStorage快照

```bash
browserfairy --snapshot-storage-once [选项]
```

对当前打开的页面进行localStorage/sessionStorage快照。

**选项**：
- `--snapshot-hostname <域名>` - 仅快照指定网站
- `--snapshot-maxlen <长度>` - 值的最大长度（默认2048）

**示例**：
```bash
# 快照所有页面
browserfairy --snapshot-storage-once

# 仅快照example.com
browserfairy --snapshot-storage-once --snapshot-hostname example.com

# 限制敏感数据长度
browserfairy --snapshot-storage-once --snapshot-maxlen 100
```

## Source Map支持

### 启用Source Map解析

```bash
# 在任何监控命令中添加 --enable-source-map
browserfairy --monitor-comprehensive --enable-source-map
browserfairy --start-monitoring --enable-source-map
```

**功能说明**：
- 自动检测JavaScript文件的Source Map
- 将压缩代码错误位置映射到源代码
- 在错误堆栈中添加`original`字段

**输出示例**：
```json
{
  "stackTrace": [{
    "function": "handleSubmit",
    "url": "bundle.min.js",
    "line": 1,
    "column": 45678,
    "original": {
      "file": "src/components/Form.jsx",
      "line": 42,
      "column": 15,
      "name": "handleSubmit"
    }
  }]
}
```

**注意事项**：
- Source Map文件必须可访问（HTTP或data URL）
- 会稍微增加内存占用（缓存Source Map）
- 失败时自动降级，保持原始堆栈信息

## 工具命令

### 测试连接

```bash
browserfairy --test-connection
```

测试与Chrome的连接状态。

### Chrome信息

```bash
browserfairy --chrome-info
```

显示Chrome版本和调试信息。

### 列出标签页

```bash
browserfairy --list-tabs
```

输出当前所有标签页的JSON信息。

## 后台管理

### 启动后台监控

```bash
# 启动
browserfairy --start-monitoring --daemon

# 或手动连接模式
browserfairy --monitor-comprehensive --daemon
```

### 查看后台进程

```bash
# 查看进程
ps aux | grep browserfairy

# 查看日志
tail -f ~/BrowserFairyData/monitor.log

# 查看PID
cat ~/BrowserFairyData/monitor.pid
```

### 停止后台监控

```bash
# 使用kill
kill $(cat ~/BrowserFairyData/monitor.pid)

# 或使用pkill
pkill -f browserfairy
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `BROWSERFAIRY_DATA_DIR` | 数据存储目录 | `~/BrowserFairyData` |
| `BROWSERFAIRY_LOG_LEVEL` | 日志级别 | `INFO` |
| `BROWSERFAIRY_CHROME_PORT` | Chrome调试端口 | `9222` |

## 完整选项列表

```bash
browserfairy --help
```

显示所有可用命令和选项。

## 常用组合

### 开发调试

```bash
# 错误调试
browserfairy --start-monitoring \
  --output errors-only \
  --data-dir ./debug

# 性能优化
browserfairy --start-monitoring \
  --output performance \
  --data-dir ./perf
```

### 生产监控

```bash
# 后台长期监控
browserfairy --start-monitoring \
  --daemon \
  --output ai-debug

# 定时分析
crontab -e
# 0 */6 * * * browserfairy --analyze-sites >> /var/log/browserfairy-analysis.log
```

### CI/CD集成

```bash
#!/bin/bash
# ci-test.sh

# 启动监控
browserfairy --start-monitoring --daemon

# 运行测试
npm test

# 收集结果
browserfairy --analyze-sites > test-report.txt

# 清理
pkill -f browserfairy
```

## 故障排查

### 调试模式

```bash
# 启用详细日志
BROWSERFAIRY_LOG_LEVEL=DEBUG browserfairy --test-connection

# 指定Chrome端口
BROWSERFAIRY_CHROME_PORT=9223 browserfairy --monitor-comprehensive
```

### 常见问题

1. **连接失败**：确保Chrome以调试模式运行
2. **权限错误**：检查数据目录权限
3. **端口冲突**：使用不同的调试端口

## 更多帮助

- [快速开始](./getting-started.md)
- [AI调试指南](./ai-debugging.md)
- [故障排查](./troubleshooting.md)
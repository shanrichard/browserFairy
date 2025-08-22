# 快速开始指南

## 系统要求

- Python 3.11 或更高版本
- Chrome/Chromium 浏览器
- macOS、Linux 或 Windows

## 安装方式

### 方式1：一键安装脚本（推荐）

```bash
curl -sSL https://raw.githubusercontent.com/shanrichard/browserfairy/main/install.sh | sh
```

这个脚本会自动：
1. 检查Python版本
2. 安装uv包管理器
3. 克隆仓库并安装依赖
4. 配置命令行工具

### 方式2：使用uv手动安装

```bash
# 安装uv（如果还没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目
git clone https://github.com/shanrichard/browserfairy.git
cd browserfairy

# 安装依赖
uv sync

# 安装为系统命令
uv run pip install -e .
```

### 方式3：使用pip安装

```bash
# 克隆项目
git clone https://github.com/shanrichard/browserfairy.git
cd browserfairy

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装
pip install -e .
```

## 验证安装

```bash
# 检查版本
browserfairy --version

# 测试连接
browserfairy --test-connection
```

## 第一次使用

### 最简单的方式：一键启动

```bash
# 推荐：自动启动Chrome并保存所有脚本源代码
browserfairy --start-monitoring --enable-source-map --persist-all-source-maps
```

这会：
- 启动一个独立的Chrome实例（不影响你的日常浏览器）
- 开始全面的性能监控
- **保存所有JavaScript脚本源代码**（包括没有Source Map的）
- 数据保存到 `~/BrowserFairyData/`
- 按Ctrl+C停止监控

### AI调试模式

如果你想配合Claude Code/Cursor使用：

```bash
# 收集错误和脚本源代码，保存到当前目录
browserfairy --start-monitoring \
  --enable-source-map \
  --persist-all-source-maps \
  --output errors-only \
  --data-dir ./debug_data
```

### 后台运行

需要长时间监控时：

```bash
# 启动后台监控（推荐：保存脚本源代码）
browserfairy --start-monitoring --enable-source-map --persist-all-source-maps --daemon

# 查看运行状态
ps aux | grep browserfairy

# 停止后台监控
pkill -f browserfairy
```

## 基本使用流程

### 1. 启动监控

```bash
# 根据需求选择一种方式
browserfairy --start-monitoring              # 完整监控
browserfairy --start-monitoring --daemon     # 后台运行
browserfairy --monitor-comprehensive         # 手动连接已有Chrome
```

### 2. 使用浏览器

正常浏览网页，BrowserFairy会自动：
- 监控所有标签页
- 按网站分类数据
- 捕获错误和性能指标

### 3. 查看数据

```bash
# 分析所有网站
browserfairy --analyze-sites

# 分析特定网站
browserfairy --analyze-sites example.com

# 直接查看原始数据
ls ~/BrowserFairyData/session_*/
```

## 数据存储位置

默认数据目录：`~/BrowserFairyData/`

结构：
```
~/BrowserFairyData/
└── session_2025-01-20_143022/      # 每次监控会话
    ├── overview.json                # 会话概览
    └── example.com/                 # 按网站分组
        ├── memory.jsonl             # 内存数据
        ├── console.jsonl            # 控制台日志
        ├── network.jsonl            # 网络请求
        └── correlations.jsonl       # 关联分析
```

### 自定义数据目录

```bash
# 通过命令参数
browserfairy --start-monitoring --data-dir /path/to/data

# 或设置环境变量
export BROWSERFAIRY_DATA_DIR=/path/to/data
browserfairy --start-monitoring
```

## 常见场景

### 场景1：调试生产环境问题

```bash
# 在生产服务器上后台运行
browserfairy --start-monitoring --daemon

# 定期分析
browserfairy --analyze-sites

# 导出数据供本地分析
tar -czf prod_data.tar.gz ~/BrowserFairyData/
```

### 场景2：性能优化

```bash
# 收集完整性能数据
browserfairy --start-monitoring --output performance

# 运行性能测试场景
# ...

# 分析结果
browserfairy --analyze-sites
```

### 场景3：CI/CD集成

```bash
# 在CI脚本中
browserfairy --start-monitoring --daemon
npm run e2e-tests
browserfairy --analyze-sites > performance-report.txt
pkill -f browserfairy
```

## 故障排除

### Chrome连接失败

```bash
# 确保Chrome正在运行调试模式
# macOS
open -a "Google Chrome" --args --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222

# Windows
chrome.exe --remote-debugging-port=9222
```

### 权限问题

```bash
# 确保有写入权限
chmod -R 755 ~/BrowserFairyData

# 或使用其他目录
browserfairy --start-monitoring --data-dir ./data
```

### Python版本问题

```bash
# 检查Python版本
python --version

# 使用pyenv安装Python 3.11
pyenv install 3.11.0
pyenv local 3.11.0
```

## 下一步

- 📖 阅读[AI辅助调试指南](./ai-debugging.md)了解如何配合AI使用
- 🔧 查看[命令参考](./commands.md)了解所有可用命令
- 📊 学习[数据分析指南](./data-analysis.md)深入理解监控数据

## 获取帮助

- 提交Issue：[GitHub Issues](https://github.com/shanrichard/browserfairy/issues)
- 查看FAQ：[常见问题](./troubleshooting.md)
- 社区讨论：[Discussions](https://github.com/shanrichard/browserfairy/discussions)
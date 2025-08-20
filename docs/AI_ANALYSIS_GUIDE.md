# BrowserFairy AI Analysis Guide - AI智能分析指南

## 目录
- [快速开始](#快速开始)
- [API Key配置](#api-key配置)
- [环境要求](#环境要求)
- [使用方法](#使用方法)
- [分析模式详解](#分析模式详解)
- [常见问题](#常见问题)
- [最佳实践](#最佳实践)

## 快速开始

BrowserFairy的AI分析功能利用Claude AI对收集的监控数据进行智能分析，帮助开发者快速定位性能问题、内存泄漏和错误根因。

### 三步启用AI分析

1. **获取API Key**
   ```bash
   # 访问Anthropic Console
   https://console.anthropic.com
   ```

2. **配置API Key（推荐使用.env文件）**
   ```bash
   # 方法A：创建.env文件（推荐，永久有效）
   cp .env.example .env
   # 编辑.env文件，填入你的API Key
   
   # 方法B：设置环境变量（临时）
   export ANTHROPIC_API_KEY="sk-ant-api03-xxx..."
   ```

3. **运行AI分析**
   ```bash
   python -m browserfairy --analyze-with-ai
   ```

## API Key配置

### 方法1：环境变量（推荐）

#### Linux/Mac
```bash
# 临时设置（当前终端会话）
export ANTHROPIC_API_KEY="your-api-key-here"

# 永久设置（添加到配置文件）
echo 'export ANTHROPIC_API_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc

# 或者使用 ~/.zshrc (如果使用zsh)
echo 'export ANTHROPIC_API_KEY="your-api-key-here"' >> ~/.zshrc
source ~/.zshrc
```

#### Windows
```powershell
# PowerShell临时设置
$env:ANTHROPIC_API_KEY="your-api-key-here"

# 永久设置（系统环境变量）
[System.Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY','your-api-key-here','User')
```

### 方法2：.env文件（推荐）

在项目根目录创建`.env`文件：
```bash
# 复制示例文件
cp .env.example .env

# 编辑.env文件，填入你的API Key
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxx...
```

**BrowserFairy会自动加载.env文件**，按以下优先级查找：
1. 当前目录的`.env`
2. 用户主目录的`.env`
3. 项目根目录的`.env`

无需修改任何代码，直接运行即可：
```bash
browserfairy --analyze-with-ai
```

### 获取API Key步骤

1. **注册账号**
   - 访问 [https://console.anthropic.com](https://console.anthropic.com)
   - 使用邮箱注册账号
   - 验证邮箱

2. **创建API Key**
   - 登录后进入API Keys页面
   - 点击"Create Key"
   - 给Key命名（如"BrowserFairy"）
   - 复制生成的Key（格式：`sk-ant-api03-xxx...`）

3. **安全提示**
   - API Key一旦创建只显示一次，请妥善保存
   - 不要将API Key提交到Git仓库
   - 定期轮换API Key以保证安全
   - 可以设置使用限额避免意外消费

## 环境要求

### Node.js要求
AI分析功能需要Node.js 18或更高版本：

```bash
# 检查Node.js版本
node --version

# 如果版本过低，请升级
# macOS (使用Homebrew)
brew install node

# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Windows
# 下载安装包：https://nodejs.org/
```

### Python依赖
所需依赖已在`pyproject.toml`中声明：
```bash
# 使用uv安装（推荐）
uv sync

# 或使用pip
pip install claude-code-sdk typing-extensions
```

## 使用方法

### 基础用法

```bash
# 分析最新的监控会话
python -m browserfairy --analyze-with-ai

# 分析指定的会话目录
python -m browserfairy --analyze-with-ai ~/BrowserFairyData/session_2025-08-20_143022

# 使用特定分析焦点
python -m browserfairy --analyze-with-ai --focus memory_leak

# 自定义分析需求
python -m browserfairy --analyze-with-ai --custom-prompt "只分析最近1小时的数据，重点关注网络请求失败"
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--analyze-with-ai [DIR]` | 启动AI分析，可选指定session目录 | 最新session |
| `--focus TYPE` | 分析焦点类型 | general |
| `--custom-prompt TEXT` | 自定义分析提示词 | 无 |

### 分析焦点类型

- `general` - 综合分析（默认）
- `memory_leak` - 内存泄漏专项分析
- `performance` - 性能瓶颈分析
- `network` - 网络性能分析
- `errors` - 错误和异常分析

### 分析报告

AI分析完成后会自动生成Markdown格式的分析报告：

**报告文件**：
- 文件名：`ai_analysis_[focus]_[timestamp].md`
- 保存位置：与监控数据相同的session目录
- 示例：`~/BrowserFairyData/session_2025-08-20_143022/ai_analysis_memory_leak_20250820_143055.md`

**报告内容**：
- 生成时间和分析参数
- 完整的分析结果
- 问题诊断和优化建议
- 源代码级的问题定位（如果有）

**查看报告**：
```bash
# 分析完成后会显示报告路径
AI分析报告已保存: /Users/xxx/BrowserFairyData/session_2025-08-20_143022/ai_analysis_general_20250820_143055.md

# 直接查看报告
cat ~/BrowserFairyData/session_*/ai_analysis_*.md
```

## 分析模式详解

### 1. 综合分析（general）
默认模式，提供全面的性能诊断：
- 内存使用趋势
- 性能瓶颈识别
- 错误统计
- 网络请求分析

```bash
python -m browserfairy --analyze-with-ai
```

### 2. 内存泄漏分析（memory_leak）
深度分析内存问题：
- 函数级内存分配统计（基于heap_sampling.jsonl）
- 源代码级泄漏定位（利用sources/目录）
- 识别常见泄漏模式：
  - 未清理的事件监听器
  - 闭包引用的大对象
  - 循环引用
  - 未销毁的定时器

```bash
python -m browserfairy --analyze-with-ai --focus memory_leak
```

示例输出：
```
发现内存泄漏问题：
1. handleClick函数（sources/app.js:245）持续分配内存
   - 每次调用分配约2MB
   - 24小时内调用1200次
   - 建议：检查是否有未清理的事件监听器

2. WebSocket连接未正确关闭
   - 位置：sources/websocket-manager.js:89
   - 影响：每个连接泄漏约500KB
   - 建议：在组件卸载时调用ws.close()
```

### 3. 性能瓶颈分析（performance）
识别影响用户体验的性能问题：
- 长任务分析（>50ms的任务）
- GC频率和耗时
- 主线程阻塞情况
- 布局抖动检测

```bash
python -m browserfairy --analyze-with-ai --focus performance
```

### 4. 网络性能分析（network）
优化API和资源加载：
- 响应时间分布（P50/P95/P99）
- 失败请求分析
- 大文件传输识别
- 请求并发分析

```bash
python -m browserfairy --analyze-with-ai --focus network
```

### 5. 错误分析（errors）
精确定位代码问题：
- 错误频率统计
- 堆栈跟踪解析
- 源代码定位（使用source maps）
- 修复建议

```bash
python -m browserfairy --analyze-with-ai --focus errors
```

## 常见问题

### Q1: 提示"API Key未配置"
**解决方案：**
1. 确认已设置环境变量：
   ```bash
   echo $ANTHROPIC_API_KEY
   ```
2. 如果为空，重新设置：
   ```bash
   export ANTHROPIC_API_KEY="your-key-here"
   ```

### Q2: 提示"Node.js版本过低"
**解决方案：**
升级到Node.js 18+：
```bash
# 使用nvm管理版本
nvm install 18
nvm use 18
```

### Q3: 分析结果不准确
**可能原因：**
- 数据收集时间太短
- 监控覆盖不全面
- 自定义prompt不够具体

**解决方案：**
```bash
# 收集更多数据
python -m browserfairy --monitor-comprehensive --duration 300

# 使用更具体的prompt
python -m browserfairy --analyze-with-ai --custom-prompt "分析memory.jsonl中JS Heap超过500MB的时间段"
```

### Q4: API调用费用问题
**费用控制建议：**
1. 使用`--focus`参数进行针对性分析
2. 避免重复分析相同数据
3. 在Anthropic Console设置使用限额
4. 定期清理旧的监控数据

### Q5: 分析速度慢
**优化建议：**
1. 使用焦点模式而非综合分析
2. 限制分析的时间范围
3. 预先筛选关键数据文件

## 最佳实践

### 1. 数据收集策略
```bash
# 开发环境：短时间密集监控
python -m browserfairy --monitor-comprehensive --duration 60

# 生产环境：长时间轻量监控
python -m browserfairy --monitor-memory --duration 3600
```

### 2. 分析工作流
```bash
# Step 1: 收集数据
python -m browserfairy --monitor-comprehensive --duration 300

# Step 2: 基础统计分析
python -m browserfairy --analyze-sites

# Step 3: AI深度分析
python -m browserfairy --analyze-with-ai --focus memory_leak

# Step 4: 验证修复效果
# 修复代码后重新监控并分析
```

### 3. 团队协作
```bash
# 开发者A：收集监控数据
python -m browserfairy --monitor-comprehensive

# 开发者B：分析数据（使用相同的API Key）
export ANTHROPIC_API_KEY="team-shared-key"
python -m browserfairy --analyze-with-ai ~/shared/BrowserFairyData/session_xxx
```

### 4. CI/CD集成
```yaml
# .github/workflows/performance.yml
- name: Run Performance Monitoring
  run: |
    python -m browserfairy --monitor-comprehensive --duration 60
    
- name: AI Analysis
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: |
    python -m browserfairy --analyze-with-ai --focus performance
```

### 5. 自定义分析示例

#### 分析特定时间段
```bash
python -m browserfairy --analyze-with-ai --custom-prompt "
只分析2025-08-20 14:00到15:00之间的数据，
重点关注：
1. 内存增长率
2. 网络请求失败率
3. Console错误数量
"
```

#### 对比分析
```bash
python -m browserfairy --analyze-with-ai --custom-prompt "
对比分析memory.jsonl中前10分钟和最后10分钟的数据，
找出内存增长的主要原因
"
```

#### 源码关联分析
```bash
python -m browserfairy --analyze-with-ai --custom-prompt "
分析heap_sampling.jsonl中的内存分配，
在sources/目录找到对应的源代码，
给出具体的代码优化建议
"
```

## 技术细节

### 数据隐私
- 所有分析在本地进行
- 只有分析prompt发送到Claude API
- 监控数据不离开本地环境
- 可以在内网环境使用（需要能访问API）

### 性能影响
- AI分析不影响监控性能
- 分析过程异步执行
- 支持中断和恢复
- 自动缓存分析结果

### 扩展性
- 支持自定义prompt模板
- 可以集成到自动化流程
- 支持批量分析多个session
- 结果可导出为报告

## 相关链接

- [Anthropic Console](https://console.anthropic.com) - API Key管理
- [Claude Documentation](https://docs.anthropic.com) - Claude API文档
- [Node.js Downloads](https://nodejs.org/) - Node.js下载
- [BrowserFairy GitHub](https://github.com/your-repo/browserfairy) - 项目主页

## 更新日志

- **v0.2.0** (2025-08-20)
  - 新增AI分析功能
  - 支持5种分析焦点
  - 集成源码映射分析
  - 自定义prompt支持
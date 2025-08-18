# BrowserFairy - 深度Web性能诊断工具

**BrowserFairy**是一款专业的Chrome性能监控工具，专为解决Web应用的深层性能问题而设计。通过Chrome DevTools Protocol (CDP)实现**无侵入式**的浏览器内部监控，自动发现内存泄漏、性能瓶颈和异常模式，为开发团队提供精准的问题定位和优化建议。

## 🎯 为什么需要BrowserFairy？

### Web性能监控的现实痛点

在现代Web开发中，性能问题往往隐藏在复杂的用户交互场景中：

- **🔥 内存泄漏隐患**：单页应用长期运行后出现卡顿、电脑发烫，但重启Chrome后短暂恢复
- **📈 性能劣化趋势**：页面初次加载正常，但使用一段时间后响应变慢，难以复现和定位  
- **🌐 多网站交互影响**：不同标签页之间的资源竞争和性能相互影响
- **⚡ 实时监控缺失**：Chrome DevTools只能在开发时临时分析，无法持续监控生产使用

### 现有工具的局限性

**Chrome DevTools**：功能强大但需要手动操作，无法自动化监控和历史对比
**传统APM工具**：关注服务器端性能，对浏览器端的深层问题（如DOM泄漏、事件监听器累积）缺乏洞察
**性能测试工具**：适合单次测试，不适合长期监控真实用户场景下的性能变化

### BrowserFairy的解决方案

BrowserFairy通过**自动化持续监控**弥补这一空白，让性能问题无处遁形：

✅ **24/7自动监控**：后台静默运行，持续收集真实使用场景下的性能数据  
✅ **Target级精准分析**：每个标签页独立会话，精确隔离不同网站的性能指标  
✅ **多维度关联分析**：自动关联内存变化、网络请求、控制台错误，发现隐藏的性能模式  
✅ **长期趋势追踪**：按网站维度组织数据，支持历史对比和趋势分析  
✅ **零配置部署**：一键启动，无需修改代码或安装浏览器插件  

## 🚀 核心技术特性

### 深度CDP集成
- **Browser级连接管理**：复用单个WebSocket连接，支持3次指数退避重试
- **Target级会话隔离**：每个标签页独立CDP session，避免数据混淆
- **事件驱动架构**：实时响应标签页创建/销毁/URL变化，自动调整监控范围

### 智能性能分析
- **内存全景监控**：JS Heap、DOM节点、事件监听器、文档和帧数的完整监控
- **网络行为追踪**：请求生命周期、响应大小、错误率的实时统计  
- **Console异常捕获**：JavaScript错误、警告、异常的自动收集和分类
- **时间窗口关联**：3秒时间窗口内的多事件智能关联分析

### 企业级数据管理
- **按网站分组**：数据按hostname自动分类，支持多网站并行监控
- **JSONL时序存储**：高效的时序数据格式，便于后续分析和可视化
- **会话化管理**：每次监控生成独立会话目录，支持历史数据对比
- **文件轮转机制**：基于大小和时间的自动文件轮转，避免单文件过大

### 高性能架构设计
- **全局并发控制**：Semaphore限制同时采样数量，确保<2% CPU开销
- **异步队列解耦**：事件接收和处理分离，避免背压影响浏览器性能
- **频率智能限制**：Console事件≤10/s，Network事件≤50/s，防止数据洪流
- **优雅降级机制**：队列满时自动丢弃部分数据，保证核心监控不中断

## 📊 实际应用场景

### 开发团队：性能瓶颈定位
```
场景：电商网站的商品详情页在用户浏览30分钟后变得卡顿

BrowserFairy发现：
• JS Heap从初始25MB增长到350MB，存在明显内存泄漏
• DOM节点数从1,200增长到15,000+，未正确清理动态内容  
• 网络请求中有大量重复的图片加载（缓存失效）
• Console中出现周期性的"Cannot read property of null"错误

结果：开发团队定位到图片懒加载组件的内存泄漏bug，修复后内存使用下降80%
```

### 产品团队：用户体验监控
```
场景：SaaS平台的仪表板页面用户反馈"越用越慢"

BrowserFairy发现：
• 页面初始加载时间2.3s，30分钟后增长到8.7s
• 数据更新时的DOM重绘时间呈线性增长趋势
• WebSocket连接出现周期性重连，影响实时数据显示
• 第三方分析SDK存在未释放的事件监听器累积

结果：产品团队优化数据更新策略，用户满意度提升40%
```

### 运维团队：生产环境监控
```
场景：企业内部系统需要长期稳定运行，避免性能劣化

BrowserFairy提供：
• 多网站并行监控：同时监控OA、CRM、ERP等内部系统
• 异常自动告警：内存增长>100MB或Console错误率>5%时通知
• 性能基线对比：与历史数据对比，发现性能退化趋势
• 影响范围分析：识别影响多个页面的全局性能问题

结果：提前发现70%的性能问题，平均故障响应时间缩短60%
```

## ⚡ 快速开始

### 1. 环境准备
```bash
# 安装Python 3.11+和uv包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目并安装依赖  
git clone <repository>
cd browserfairy
uv sync

# 安装为系统命令
uv run pip install -e .
```

### 2. 一键启动监控 🎯 **最简单方式**
```bash
# 🚀 一键启动 - 自动启动Chrome并开始监控
browserfairy --start-monitoring

# 🔁 后台运行 - 启动后可以关闭终端继续工作
browserfairy --start-monitoring --daemon
```

**就这么简单！** BrowserFairy会自动：
- 启动独立的Chrome实例（不影响你现有的浏览器）
- 开始综合性能监控（内存 + 网络 + Console + 关联分析）
- 按网站分类保存监控数据
- Chrome关闭时自动停止监控

### 3. 传统方式（需要手动启动Chrome）
如果你更喜欢手动控制，也可以使用传统方式：
```bash
# 先手动启动Chrome调试模式
# macOS: open -a 'Google Chrome' --args --remote-debugging-port=9222
# Linux: google-chrome --remote-debugging-port=9222  
# Windows: chrome.exe --remote-debugging-port=9222

# 然后连接监控
browserfairy --monitor-comprehensive
browserfairy --monitor-comprehensive --daemon  # 后台模式
```

### 4. 其他实用命令
```bash
# 测试连接
browserfairy --test-connection

# 分析已收集的数据  
browserfairy --analyze-sites                    # 所有网站概览
browserfairy --analyze-sites example.com        # 特定网站详情

# 实时监控（开发调试用）
browserfairy --monitor-tabs                     # 标签页变化
browserfairy --monitor-memory                   # 内存使用情况

# DOMStorage快照 - 调试网站存储问题
browserfairy --snapshot-storage-once            # 所有打开页面的存储快照
browserfairy --snapshot-storage-once \
  --snapshot-hostname example.com              # 仅特定网站
browserfairy --snapshot-storage-once \
  --snapshot-maxlen 512                        # 限制值长度（默认2048字符）
```

### 5. 查看结果
监控数据自动保存到 `~/BrowserFairyData/` 目录：

**数据文件结构：**
```
~/BrowserFairyData/
├── session_2025-08-16_143022/     # 监控会话目录
│   ├── overview.json              # 会话概览信息
│   ├── example.com/               # 按网站分组
│   │   ├── memory.jsonl          # 内存监控时序数据
│   │   ├── console.jsonl         # Console日志和异常
│   │   ├── network.jsonl         # 网络请求生命周期
│   │   ├── gc.jsonl              # 垃圾回收（GC）事件
│   │   ├── storage.jsonl         # 存储数据：配额/DOMStorage事件/手动快照
│   │   └── correlations.jsonl    # 跨指标关联分析
│   └── trading.site.com/
│       └── ...                   # 其他监控网站
├── monitor.log                    # daemon模式运行日志
└── monitor.pid                    # 后台进程PID
```

### ✅ 去重与事件唯一标识 `event_id`（新增）
- 目的：为 memory / console / network 三类事件生成稳定、轻量的唯一标识，便于后续去重、比对与快速聚合；不改变任何原始字段，仅新增一个辅助字段。
- 算法：使用 Python 标准库 `hashlib.blake2s` 生成短摘要（10字节→20位hex），将少量关键字段按固定顺序拼接后计算；相同输入→相同 `event_id`，不含随机因素。
- 性能：计算量微秒级，远小于 JSON 序列化与磁盘写入（毫秒级），对高频场景开销可忽略。

生成规则（按事件类型）：
- memory（写入 `{hostname}/memory.jsonl`）
  - 参与字段：`type, hostname, timestamp, targetId, sessionId, url`
- console（写入 `{hostname}/console.jsonl`）
  - 参与字段：`type=console, hostname, timestamp, level, message, source.url, source.line`
- exception（同 console 文件）
  - 参与字段：`type=exception, hostname, timestamp, message, source.url, source.line, source.column`
- network_request_start（写入 `{hostname}/network.jsonl`）
  - 参与字段：`type=network_request_start, hostname, timestamp, requestId, method, url`
- network_request_complete（同上）
  - 参与字段：`type=network_request_complete, hostname, timestamp, requestId, status, url`
- network_request_failed（同上）
  - 参与字段：`type=network_request_failed, hostname, timestamp, requestId, url, errorText`

使用建议：
- 去重：将 `event_id` 作为主键（或唯一索引）可直接过滤重复记录。
- 聚合：同一网络请求的不同阶段（start/complete/failed）会有不同 `event_id`，若要聚合同一请求，请用 `requestId` 关联。
- 兼容性：`event_id` 为新增字段，旧的分析脚本可以忽略它；当需要确保“没有重复数据”时，可基于此字段简单检查去重情况。


**实时监控日志：**
```bash
# 查看实时监控状态
$ tail -f ~/BrowserFairyData/monitor.log
[2025-08-16 14:30:25] Chrome started on port 9222
[2025-08-16 14:30:28] Monitoring started
[2025-08-16 14:35:12] Console Error: TypeError: Cannot read property 'value' of null
[2025-08-16 14:36:33] Large Request: https://api.trading.com/data (5.2MB)
[2025-08-16 14:37:15] Large Response: https://cdn.example.com/bundle.js (3.1MB)
[2025-08-16 14:42:18] Correlation: 5 events correlated

# 分析数据（监控结束后）
$ browserfairy --analyze-sites
BrowserFairy 数据分析概览
==================================================
发现监控会话: 3 个

监控网站组: 2 个

example.com:
  域名: example.com
  监控会话: 2 个
  总记录数: 1247
  数据类型: console, correlations, memory, network

trading.site.com:
  域名: trading.site.com  
  监控会话: 1 个
  总记录数: 892
  数据类型: console, memory, network
```

## 🔧 核心功能一览

### 📊 监控能力矩阵
| 监控维度 | 具体指标 | 检测能力 |
|---------|---------|---------|
| 🧠 **内存监控** | JS Heap, DOM节点, 事件监听器 | 内存泄漏、DOM累积 |
| 🌐 **网络分析** | 请求大小、响应时间、错误率 + **调用栈关联** | 性能瓶颈、资源浪费、**代码定位** |
| ⚠️ **Console监控** | JS错误、警告、异常 | 代码质量、运行异常 |
| 🧹 **GC监控** | 堆使用显著下降、GC关键字日志 | GC频率、长GC提示（近似） |
| 💾 **存储跟踪** | 配额监控（含页面兜底）/DOMStorage事件/手动快照 | 存储空间与键值变更追踪 |
| 🔗 **关联分析** | 跨指标时间窗口关联 | 性能模式识别 |
| 📈 **趋势分析** | 历史数据对比、P95统计 | 性能退化预警 |

### 🎯 命令功能全览
```bash
# 🚀 一键启动系列
--start-monitoring              # 自动启动Chrome + 综合监控
--start-monitoring --daemon     # 后台运行模式

# 📊 监控模式系列  
--monitor-comprehensive         # 手动连接 + 综合监控
--monitor-memory               # 纯内存使用监控
--monitor-tabs                 # 标签页变化监控
--start-data-collection        # 基础数据收集

# 🔍 分析工具系列
--analyze-sites                # 所有网站性能概览
--analyze-sites example.com    # 特定网站详细分析

# ⚙️ 工具命令系列
--test-connection              # 连接测试
--chrome-info                  # Chrome版本信息
--list-tabs                    # 当前标签页列表
--snapshot-storage-once        # DOMStorage快照（调试存储问题）
```

### 💾 存储监控说明

#### 自动存储监控（综合监控模式下）
- **配额监控**：优先使用浏览器级 API；若遇到环境限制会自动回退到页面级 `navigator.storage.estimate()`，尽快写入 `storage.jsonl`
- **DOMStorage 事件**：自动监听 `localStorage/sessionStorage` 的键变更事件（新增/更新/移除/清空），记录在 `storage.jsonl`

#### DOMStorage快照工具（`--snapshot-storage-once`）
**功能说明**：对当前打开的网页进行localStorage和sessionStorage的完整数据快照，用于调试存储相关问题。

**典型使用场景**：
- 🔍 **诊断存储异常**：网站功能异常时，快速查看localStorage/sessionStorage中的数据状态
- 📊 **分析缓存数据**：了解网站在浏览器中缓存了哪些数据，数据量有多大
- 🐛 **调试状态问题**：检查用户状态、会话信息、临时数据是否正确存储
- 🔄 **对比存储变化**：在操作前后分别快照，对比存储数据的变化

**数据内容**：
- **存储配额**：通过 `navigator.storage.estimate()` 获取的quota（总配额）和usage（已使用量）
- **localStorage数据**：所有键值对，包括键名和对应的值
- **sessionStorage数据**：当前会话的所有键值对
- **安全截断**：超长值自动截断（默认2048字符），避免敏感数据泄露

**输出格式**（保存到 `storage.jsonl`）：
```json
{
  "type": "domstorage_snapshot",
  "timestamp": "2025-08-16T14:30:25.123Z",
  "hostname": "example.com",
  "targetId": "1234ABCD",
  "origin": "https://example.com",
  "data": {
    "estimate": {
      "quota": 137438953472,
      "usage": 524288
    },
    "local": [
      {"key": "user_preferences", "value": "{\"theme\":\"dark\",\"lang\":\"zh\"}"},
      {"key": "auth_token", "value": "eyJhbGciOiJS...[truncated]"}
    ],
    "session": [
      {"key": "temp_cart", "value": "[{\"id\":1,\"qty\":2}]"}
    ]
  }
}
```

**参数说明**：
- `--snapshot-hostname`：仅对指定hostname的页面进行快照（如 example.com）
- `--snapshot-maxlen`：单个值的最大长度（默认2048），超出部分显示`[truncated]`

⚠️ **安全提醒**：快照可能包含敏感信息（如token、密码、个人数据），建议：
- 仅用于本地调试，不要分享给他人
- 使用 `--snapshot-maxlen` 限制值长度，减少敏感信息暴露
- 快照完成后及时清理不需要的数据文件

### 🔍 网络调用栈关联（新增）
**智能触发机制**：仅对性能问题相关的网络请求收集完整的JavaScript调用栈，帮助精确定位代码位置。

**触发条件**：
- **大上传**：postData > 100KB → `large_upload`
- **大下载**：响应大小 > 100KB → `large_download`  
- **高频API**：同一端点调用 > 50次 → `high_frequency_api_{count}`
- **重复资源**：同一资源加载 > 5次且单次 > 10KB → `repeated_resource_{count}`

**调用栈信息**：
- **主调用栈**：最多30帧，包含函数名、文件URL、行号、列号
- **异步调用栈**：最多15层，跨Promise/setTimeout等异步边界
- **性能影响**：仅对~2.7%的请求收集详细栈，97%+请求零开销

**数据格式**（扩展现有network.jsonl）：
```json
{
  "type": "network_request_complete",
  "url": "https://api.com/export.json",
  "detailedStack": {
    "enabled": true,
    "reason": "large_download",
    "frames": [
      {
        "functionName": "ComponentA.fetchLargeData",
        "url": "https://app.js",
        "lineNumber": 42,
        "columnNumber": 15
      }
    ],
    "asyncFrames": [...],
    "truncated": false,
    "collectionTime": "2025-08-18T14:51:26.789Z"
  }
}
```

**典型应用场景**：
- 定位"某组件初始化时意外触发5.2MB数据下载"的具体代码路径
- 发现无用或重复API调用的JavaScript发起位置
- 追踪高频请求背后的业务逻辑调用链路

### 🏗 技术架构特点

**完整监控服务架构（1-8）：**
```
BrowserFairyService (一键启动协调器)
├── ChromeInstanceManager - 独立Chrome实例管理
├── monitor_comprehensive() - 复用现有监控逻辑
│   ├── ChromeConnector - CDP连接管理  
│   ├── TabMonitor - 标签页生命周期
│   ├── MemoryMonitor - 内存性能收集
│   ├── DataManager - 数据写入和存储监控
│   └── ComprehensiveCollector - Console/Network/关联
└── SiteDataManager - 数据分析和分组
```

**性能优化策略：**
- **全局并发控制**：Semaphore限制同时采样数（8个），确保<2% CPU开销
- **异步队列解耦**：事件接收和处理分离，避免背压影响浏览器性能
- **频率智能限制**：Console≤10/s，Network≤50/s，防止数据洪流
- **Target级会话隔离**：每个标签页独立CDP session，精确隔离不同网站

## 🎪 与其他工具对比

| 功能特性 | Chrome DevTools | 传统APM | BrowserFairy |
|---------|---------------|---------|-------------|
| 浏览器深度监控 | ✅ 手动 | ❌ 无 | ✅ 自动化 |
| 长期趋势分析 | ❌ 无 | ✅ 服务端 | ✅ 客户端 |
| 多标签页隔离 | ❌ 混合 | ❌ 无 | ✅ 精确隔离 |
| 零代码部署 | ✅ 是 | ❌ 需集成 | ✅ 是 |
| 实时关联分析 | ❌ 手动 | ⚠️ 有限 | ✅ 自动 |
| 历史数据对比 | ❌ 无 | ✅ 有 | ✅ 文件化 |

## 🛠 开发和贡献

BrowserFairy采用现代Python异步架构，欢迎开发者参与贡献：

```bash
# 开发环境设置
uv sync --dev

# 运行测试套件
uv run pytest

# 代码质量检查  
uv run pytest --cov=browserfairy
```

### 项目结构
```
browserfairy/
├── core/           # CDP连接和Chrome实例管理
├── monitors/       # 各类监控器（内存、控制台、网络）
├── analysis/       # 关联分析和性能诊断
├── data/          # 数据写入和会话管理
└── utils/         # 跨平台工具和路径管理
```

## 📜 许可证

[待补充许可证信息]

---

**⚡ 立即体验：**
```bash
# 🚀 30秒极速体验（全自动）
browserfairy --start-monitoring --duration 300

# 📊 查看监控结果
browserfairy --analyze-sites

# 🔁 长期后台监控（推荐）
browserfairy --start-monitoring --daemon
```

**BrowserFairy让Web性能问题无处遁形，为您的用户体验保驾护航。**

---

**🎯 项目状态：** 功能完整，148个测试全部通过 ✨
**📦 一键部署：** 零配置启动，自动Chrome实例管理
**🔍 数据洞察：** 按网站分组，支持历史趋势分析

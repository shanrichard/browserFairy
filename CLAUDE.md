# BrowserFairy - Chrome性能监控工具

## 项目概述

BrowserFairy是一个Chrome性能监控工具，用于帮助开发团队定位Web应用的性能问题。通过Chrome DevTools Protocol (CDP)收集浏览器实时性能数据，按网站维度分析内存、性能、网络等指标，最终生成用户友好的分析报告供开发团队诊断问题。

## 核心问题

- Web程序在浏览器运行一段时间后变卡、电脑发烫、页面加载慢
- 重启Chrome能暂时解决问题，但断断续续存在快一年
- 需要工具来发现和定位根本问题，而不是简单解决表面症状
- 部署模式：用户端收集数据 → 手动发送给开发团队 → AI工具分析

## 技术栈

- **核心**：Python 3.11+ + asyncio + Chrome DevTools Protocol
- **连接**：websockets + httpx
- **数据**：JSON/JSONL格式，按网站维度组织
- **包管理**：uv
- **测试**：pytest + pytest-asyncio

## 当前进度（截止2025-08-16）

### ✅ 已完成任务

1. **1-1 项目基础设施和CDP基本连接** - 已完成 ✅
   - ChromeConnector类实现Browser级WebSocket连接和**sessionId注入**
   - 支持Chrome端点发现和连接验证
   - 重连机制（3次指数退避重试，每次重新发现端点）
   - WebSocket任务生命周期管理和连接丢失回调机制
   - 跨平台错误提示（macOS/Windows/Linux差异化命令）
   - **子任务1-1-1**: ChromeInstanceManager独立Chrome实例管理器完成
   - **子任务1-1-2**: 后台daemon模式和日志管理完成
   - CLI命令：`--test-connection`

2. **1-2 简单的Chrome信息获取器** - 已完成 ✅
   - 获取Chrome版本信息：`--chrome-info`
   - 获取标签页列表：`--list-tabs`
   - JSON格式输出，保持CDP字段一致

3. **1-3 标签页列表监控器** - 已完成 ✅
   - 实时监控标签页创建/关闭/URL变化
   - 事件监听 + 轮询兜底机制
   - 状态一致性锁保护（解决并发竞态）
   - 输出改为回调机制（职责分离，便于后续集成）
   - URL过滤支持Edge浏览器，基础域名解析和噪声过滤
   - CLI命令：`--monitor-tabs`

4. **1-4 单个性能指标收集器** - 已完成 ✅
   - MemoryCollector类实现Target.attachToTarget个人会话
   - 完整内存指标收集：JS heap、DOM节点、事件监听器、文档、帧数
   - 性能指标：布局计数/耗时、样式重计算、脚本执行时间
   - 全局并发控制（Semaphore限制同时采样数量）
   - MemoryMonitor管理多标签页收集器（最大50个，LRU淘汰）
   - CLI命令：`--monitor-memory`

5. **1-5 数据文件写入器与存储监控** - 已完成 ✅
   - DataWriter按网站维度组织JSONL时序数据写入
   - 文件轮转机制（大小/时间双重触发）
   - DataManager集成文件写入和存储监控
   - StorageMonitor实现IndexedDB配额监控和警告
   - 完整的会话目录结构（~/BrowserFairyData/session_YYYY-MM-DD_HHMMSS/）
   - CLI命令：`--start-data-collection`

6. **1-6 多指标整合收集器** - 已完成 ✅
   - ConsoleMonitor：Console日志和异常监控
   - NetworkMonitor：网络请求生命周期监控
   - EventLimiter：事件频率限制（Console≤10/s，Network≤50/s）
   - SimpleCorrelationEngine：时间窗口关联分析
   - MemoryCollector综合模式集成（enable_comprehensive参数）
   - 完整端到端验证和CLI集成
   - CLI命令：`--monitor-comprehensive` (支持 `--daemon` 后台模式)

7. **1-7 按网站分组的数据管理器** - 已完成 ✅
   - SiteDataManager实现数据组织和查询功能
   - 极简域名分组算法（处理www和m前缀）
   - P95统计分析（简单排序法）
   - 按网站维度的内存统计和汇总
   - 跨会话数据聚合和对比分析
   - CLI命令：`--analyze-sites [hostname]`

8. **2-1 小幅事件和I/O优化** - 已完成 ✅
   - TabMonitor事件卸载修复：正确传递handler参数，避免误删其他组件事件处理器
   - DataWriter延迟同步：添加enable_delayed_sync选项，线程安全的批量fsync策略
   - 轮转前数据安全：无条件fsync确保文件重命名时数据完整性
   - DataManager集成：会话结束时强制同步，保证延迟模式数据落盘
   - **技术亮点**：最小影响原则，默认行为完全不变，向下兼容

9. **2-3-12 HeapProfiler内存采样分析** - 已完成 ✅
   - HeapSamplingMonitor类：轻量级内存分配采样，基于GCMonitor架构模式
   - 函数级内存分配统计：Top 10热点函数，精确定位内存泄漏源头
   - 完整MemoryCollector集成：综合监控模式自动启用HeapProfiler采样
   - DataManager和CLI数据流支持：heap_sampling.jsonl按网站维度存储
   - 保守性能参数：64KB采样间隔，60秒收集周期，<2%性能影响
   - **核心价值**：解决"不知道具体是哪个组件或函数导致内存泄漏"的关键痛点

### 📋 待完成任务

**1-8 完整监控服务** - 🎯 **最后一个核心任务**
   - BrowserFairyService主服务协调器（集成所有已完成组件）
   - 独立Chrome实例启动和生命周期绑定（使用1-1-1的ChromeInstanceManager）
   - 一键启动后台监控（`--start-monitoring`命令）
   - Chrome关闭自动停止监控
   - 统一的状态回调和日志记录
   - **技术架构**：所有功能模块已就绪，只需实现服务层协调和CLI集成

### 📊 技术状态

**测试覆盖**：163个测试用例全部通过，覆盖所有完成功能（包括1-6综合监控、1-7数据分析、2-1优化修复、2-3-12 HeapProfiler采样）

**性能基准**（已实现功能）：
- CPU开销：基础内存监控 <2%
- 内存占用：每标签页 <15MB
- 并发限制：全局8个同时采样，50个收集器上限
- 数据效率：元数据级监控，不抓取完整body

**架构亮点**：
- Target级会话隔离，精确多标签页监控
- 异步队列架构，避免背压阻塞
- 事件频率控制和队列满时优雅降级
- sessionId过滤支持，解决多会话事件混乱
- 模块化设计，每个监控器独立可测试

## 核心架构

### 数据流向（当前实现）
```
Chrome Browser (--remote-debugging-port=9222)
    ↓ WebSocket Connection (Browser级)
ChromeConnector - 管理连接和事件分发 + sessionId注入
    ↓ Target Sessions (个别标签页)
MemoryCollector (基础模式) - 收集内存/性能数据
    ↓ 按网站维度
DataManager + DataWriter - 写入JSONL文件 (~/BrowserFairyData/)
    ↓ 用户手动传输
开发团队 + Claude Code 分析

# 1-6综合模式（已实现）+ 2-3-12 HeapProfiler采样
MemoryCollector (综合模式) - enable_comprehensive=True
    ├── Console/Network/GC事件 → EventQueue → 关联分析 → DataManager
    ├── HeapSamplingMonitor → HeapProfiler采样 → heap_sampling.jsonl
    └── 基础内存收集（保持不变）

# 1-7数据分析（已实现）
SiteDataManager - 按网站维度组织和分析数据
    ├── 会话/网站数据查询
    ├── 域名分组和统计分析
    └── P95性能指标计算
```

### 目录结构（当前实现）
```
browserfairy/
├── __init__.py
├── __main__.py         # python -m browserfairy 入口
├── cli.py              # CLI逻辑实现  
├── core/
│   ├── __init__.py
│   ├── connector.py     # Chrome连接器 + sessionId注入
│   └── chrome_instance.py  # Chrome实例管理器
├── data/
│   ├── __init__.py
│   ├── writer.py        # JSONL文件写入器
│   ├── manager.py       # 数据管理协调器
│   └── site_manager.py  # 网站数据分析器
├── monitors/
│   ├── __init__.py
│   ├── tabs.py          # 标签页监控器
│   ├── memory.py        # 内存收集器（支持综合模式）
│   ├── console.py       # Console日志监控器
│   ├── network.py       # 网络请求监控器
│   ├── event_limiter.py # 事件频率限制器
│   └── storage.py       # 存储配额监控器
├── analysis/
│   ├── __init__.py
│   └── correlation.py   # 简单关联分析引擎
└── utils/
    ├── __init__.py
    └── paths.py         # 跨平台路径工具
```

### 数据存储结构（已实现）
```
~/BrowserFairyData/
├── session_2025-08-16_143022/
│   ├── overview.json              # 会话概览
│   ├── storage_global.jsonl       # 全局存储配额数据
│   ├── example.com/
│   │   ├── memory.jsonl          # 内存监控数据
│   │   ├── console.jsonl         # Console日志（1-6）
│   │   ├── network.jsonl         # 网络请求数据（1-6）
│   │   ├── correlations.jsonl    # 关联分析结果（1-6）
│   │   ├── gc.jsonl              # GC事件数据
│   │   ├── longtask.jsonl        # 长任务检测数据
│   │   └── heap_sampling.jsonl   # 内存采样分析数据（2-3-12）
│   └── news.site.com/
│       └── ...
```

## 关键技术要点

### 1. Chrome DevTools Protocol集成
- Browser级会话用于全局操作（Target.getTargets, Target.setDiscoverTargets）
- Target级会话用于具体性能数据收集（Runtime.evaluate, Performance.getMetrics等）
- 事件监听 + 轮询兜底保证数据完整性

### 2. 多标签页数据分离策略
- 通过targetId和URL的hostname字段区分网站
- 每个Target创建独立的CDP session进行数据收集
- 处理单页应用的路由变化（通过Target.targetInfoChanged）

### 3. 性能影响最小化
- 异步IO避免阻塞Chrome性能
- 数据采集间隔控制（5秒一次性能快照）
- 监控工具本身CPU占用目标 <2%, 内存占用 <50MB

## 使用方式

### 基础连接测试
```bash
# 测试Chrome连接
python -m browserfairy --test-connection

# 获取Chrome版本信息
python -m browserfairy --chrome-info

# 列出当前标签页
python -m browserfairy --list-tabs
```

### 实时监控
```bash
# 实时监控标签页变化
python -m browserfairy --monitor-tabs

# 内存使用监控
python -m browserfairy --monitor-memory

# 完整数据收集（内存+存储监控+文件写入）
python -m browserfairy --start-data-collection

# 综合监控（内存+Console+网络+关联分析）
python -m browserfairy --monitor-comprehensive

# 后台daemon模式
python -m browserfairy --monitor-comprehensive --daemon
```

### 数据分析
```bash
# 分析所有网站数据概览
python -m browserfairy --analyze-sites

# 分析特定网站详情
python -m browserfairy --analyze-sites example.com
```

### Chrome启动（需要调试端口）
```bash
# Windows
chrome.exe --remote-debugging-port=9222

# Mac/Linux  
google-chrome --remote-debugging-port=9222
```

## 开发和测试

### 依赖管理
```bash
# 安装依赖
uv sync --dev

# 运行测试
uv run pytest

# 运行特定测试
uv run pytest tests/test_connector.py -v
```

### 测试覆盖
- 单元测试：connector、tabs、paths等模块
- 集成测试：需要Chrome实例的端到端测试
- 性能测试：验证监控工具本身的性能开销

## 下一步计划

1. **当前任务**：实现1-8完整监控服务
   - BrowserFairyService主服务协调器
   - 独立Chrome实例集成（使用1-1-1 ChromeInstanceManager）
   - 一键启动命令（`--start-monitoring`）
   - Chrome生命周期绑定和自动停止

2. **最终目标**：用户友好的打包部署，生成单个可执行文件

## 调试建议

- 使用`--verbose`参数查看详细日志
- Chrome必须以调试模式启动：`--remote-debugging-port=9222`
- 确保数据目录权限正确：`~/BrowserFairyData/`
- 测试时多开几个不同网站的标签页验证数据分离
- 出现连接问题时检查端口占用和Chrome进程状态
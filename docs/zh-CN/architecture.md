# 技术架构

## 系统架构概览

BrowserFairy采用模块化的异步架构，通过Chrome DevTools Protocol (CDP)实现无侵入式的浏览器监控。

```
┌─────────────────────────────────────────────────┐
│                  用户浏览器                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │  Tab 1   │  │  Tab 2   │  │  Tab 3   │      │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘      │
│        │              │              │           │
│        └──────────────┼──────────────┘           │
│                       ▼                          │
│            Chrome DevTools Protocol              │
│                  (Port 9222)                     │
└────────────────────┬─────────────────────────────┘
                     │ WebSocket
                     ▼
┌─────────────────────────────────────────────────┐
│              BrowserFairy Service                │
│  ┌─────────────────────────────────────────┐    │
│  │         ChromeConnector (核心)           │    │
│  │  - WebSocket连接管理                     │    │
│  │  - SessionId注入                        │    │
│  │  - 事件分发                             │    │
│  └────────────┬────────────────────────────┘    │
│               │                                  │
│  ┌────────────┼────────────────────────────┐    │
│  │            ▼                            │    │
│  │  ┌──────────────┐  ┌──────────────┐    │    │
│  │  │ TabMonitor   │  │MemoryMonitor │    │    │
│  │  └──────────────┘  └──────────────┘    │    │
│  │  ┌──────────────┐  ┌──────────────┐    │    │
│  │  │NetworkMonitor│  │ConsoleMonitor│    │    │
│  │  └──────────────┘  └──────────────┘    │    │
│  └─────────────────────────────────────────┘    │
│                       │                          │
│                       ▼                          │
│  ┌─────────────────────────────────────────┐    │
│  │            DataManager                  │    │
│  │  - 数据聚合和路由                       │    │
│  │  - 文件写入管理                         │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
                        │
                        ▼
                 JSONL数据文件
```

## 核心组件

### 1. ChromeConnector - CDP连接器

**职责**：
- 管理与Chrome的WebSocket连接
- 处理Browser级别的CDP会话
- 实现sessionId注入机制
- 分发事件到各个监控器

**关键特性**：
- 自动重连机制（3次指数退避）
- 连接状态管理
- 错误恢复策略
- 跨平台兼容

```python
class ChromeConnector:
    async def connect(self):
        # 发现Chrome端点
        # 建立WebSocket连接
        # 注入sessionId处理
        
    async def send_command(self, method, params):
        # 发送CDP命令
        # 处理响应
```

### 2. Monitor层 - 专项监控器

每个监控器负责特定类型的数据收集：

#### TabMonitor - 标签页监控
- 监听标签页创建/关闭/URL变化
- 管理Target生命周期
- 触发其他监控器的启动/停止

#### MemoryMonitor - 内存收集器
- 管理多个MemoryCollector实例
- 实现LRU淘汰策略（最多50个）
- 全局并发控制（Semaphore）

#### MemoryCollector - 单标签页内存收集
- Target级CDP会话
- 5秒间隔采样
- 综合模式支持（含Console/Network）
- 事件监听器泄漏检测

#### NetworkMonitor - 网络监控
- HTTP请求生命周期
- WebSocket帧监控
- 调用栈智能收集
- 大文件传输检测

#### ConsoleMonitor - 控制台监控
- JavaScript错误捕获
- 日志分级处理
- 异常堆栈追踪

### 3. DataManager - 数据管理层

**职责**：
- 接收各监控器数据
- 按网站分组路由
- 管理DataWriter实例
- 协调存储监控

**数据流**：
```
监控器 → DataManager → DataWriter → JSONL文件
                ↓
          StorageMonitor
```

### 4. ChromeInstanceManager - Chrome实例管理

**功能**：
- 启动独立Chrome进程
- 配置调试端口
- 生命周期管理
- 崩溃恢复

```python
class ChromeInstanceManager:
    async def start_chrome(self):
        # 查找Chrome可执行文件
        # 启动调试模式
        # 返回调试端口
        
    async def stop_chrome(self):
        # 优雅关闭Chrome
```

## 数据流架构

### 事件流转过程

1. **事件产生**：Chrome内部事件（页面加载、网络请求、控制台输出等）
2. **CDP传输**：通过WebSocket推送到BrowserFairy
3. **SessionId过滤**：根据sessionId路由到对应监控器
4. **数据处理**：监控器解析和增强数据
5. **队列缓冲**：异步队列避免背压
6. **数据写入**：按网站分组写入JSONL文件

### 并发控制机制

```python
# 全局采样并发限制
GLOBAL_SEMAPHORE = asyncio.Semaphore(8)

# 事件队列（避免阻塞）
EVENT_QUEUE = asyncio.Queue(maxsize=1000)

# 频率限制
CONSOLE_LIMITER = RateLimiter(10)  # 10/秒
NETWORK_LIMITER = RateLimiter(50)  # 50/秒
```

## 关键技术决策

### 1. 为什么选择CDP？

**优势**：
- 无需修改应用代码
- 获取浏览器深层数据
- 实时事件推送
- 官方协议稳定

**挑战与解决**：
- 连接管理 → 自动重连机制
- 多标签页 → Target级会话隔离
- 数据量大 → 频率限制和采样

### 2. 为什么是JSONL格式？

- **流式处理**：逐行读取，内存友好
- **追加写入**：高效的时序数据存储
- **AI友好**：结构化数据易于解析
- **工具支持**：jq等工具原生支持

### 3. SessionId注入机制

**问题**：CDP事件缺少会话标识，难以区分来源

**解决方案**：
```javascript
// 在Browser级别注入
const originalEmit = this.emit;
this.emit = function(event, params) {
    if (params && params.sessionId) {
        // 注入sessionId到事件参数
    }
    return originalEmit.call(this, event, params);
};
```

### 4. 事件监听器泄漏检测

**两阶段策略**：
1. **轻量统计**：每次采样都统计分布
2. **深度分析**：增长>20时异步分析源码位置

```python
async def analyze_listeners():
    # 阶段1：统计
    stats = await get_listener_stats()
    
    # 阶段2：定位（条件触发）
    if stats['growth'] > 20:
        sources = await get_listener_sources()
        return identify_leak_suspects(sources)
```

## 性能优化策略

### 1. 资源控制

- **CPU优化**：
  - 异步IO避免阻塞
  - 批量处理减少开销
  - 智能采样降低频率

- **内存优化**：
  - 流式数据处理
  - LRU缓存淘汰
  - 队列大小限制

### 2. 数据优化

- **过滤机制**：
  ```python
  OUTPUT_FILTERS = {
      'errors-only': ['console:error', 'exception'],
      'performance': ['memory', 'gc', 'network:complete'],
      'minimal': ['console:error', 'exception']
  }
  ```

- **去重策略**：
  - 基于event_id的唯一标识
  - Blake2s哈希算法
  - 关键字段组合

### 3. 智能降级

当系统压力过大时：
1. 丢弃低优先级事件
2. 增加采样间隔
3. 减少并发数量
4. 暂停非关键监控

## 扩展性设计

### 插件架构

新监控器只需实现标准接口：

```python
class BaseMonitor:
    async def start(self, connector: ChromeConnector):
        """启动监控"""
        
    async def stop(self):
        """停止监控"""
        
    async def on_event(self, event: dict):
        """处理事件"""
```

### 数据管道

支持自定义数据处理：

```python
class DataPipeline:
    def __init__(self):
        self.processors = []
        
    def add_processor(self, processor):
        self.processors.append(processor)
        
    async def process(self, data):
        for processor in self.processors:
            data = await processor(data)
        return data
```

## 部署架构

### 单机部署

```
browserfairy --start-monitoring
    ├── 启动Chrome实例
    ├── 建立CDP连接
    ├── 创建监控器
    └── 写入本地文件
```

### Docker部署

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y chromium
COPY . /app
WORKDIR /app
RUN pip install -e .
CMD ["browserfairy", "--start-monitoring"]
```

### CI/CD集成

```yaml
# .github/workflows/performance.yml
- name: Start BrowserFairy
  run: browserfairy --start-monitoring --daemon
  
- name: Run E2E Tests
  run: npm test
  
- name: Analyze Results
  run: browserfairy --analyze-sites
```

## 安全考虑

### 1. 数据隐私

- 敏感数据截断（如token）
- 本地存储，不上传云端
- 可配置的数据过滤

### 2. 资源隔离

- 独立Chrome实例
- 用户数据目录隔离
- 沙箱环境运行

### 3. 权限控制

- 只读监控，不修改页面
- 文件权限最小化
- 无网络上传功能


## 技术栈

- **语言**：Python 3.11+
- **异步框架**：asyncio
- **WebSocket**：websockets
- **HTTP客户端**：httpx
- **数据格式**：JSON/JSONL
- **测试**：pytest + pytest-asyncio
- **包管理**：uv

## 相关文档

- [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)
- [WebSocket协议](https://tools.ietf.org/html/rfc6455)
- [JSONL规范](https://jsonlines.org/)
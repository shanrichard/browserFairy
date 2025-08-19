# BrowserFairy 数据分析完全指南

## 📋 目录

- [概述](#概述)
- [数据文件结构](#数据文件结构)
- [核心数据类型详解](#核心数据类型详解)
  - [1. 内存监控数据 (memory.jsonl)](#1-内存监控数据-memoryjsonl)
  - [2. 网络请求数据 (network.jsonl)](#2-网络请求数据-networkjsonl)
  - [3. Console日志数据 (console.jsonl)](#3-console日志数据-consolejsonl)
  - [4. 垃圾回收数据 (gc.jsonl)](#4-垃圾回收数据-gcjsonl)
  - [5. 存储监控数据 (storage.jsonl)](#5-存储监控数据-storagejsonl)
  - [6. 关联分析数据 (correlations.jsonl)](#6-关联分析数据-correlationsjsonl)
- [高级功能分析](#高级功能分析)
  - [网络请求调用栈分析](#网络请求调用栈分析)
  - [DOMStorage快照分析](#domstorage快照分析)
  - [事件去重机制](#事件去重机制)
- [典型问题诊断示例](#典型问题诊断示例)
- [数据分析最佳实践](#数据分析最佳实践)

---

## 概述

BrowserFairy 生成的监控数据采用 **JSONL格式**（JSON Lines），每行一个独立的JSON对象，按时间顺序记录。这种格式便于流式处理和增量分析。

**重要提示**：很多高级功能的数据 **不在文件开头**，需要完整读取文件才能发现所有有价值的信息。

## 数据文件结构

```
~/BrowserFairyData/
└── session_2025-08-16_143022/        # 监控会话目录
    ├── overview.json                  # 会话概览信息
    ├── example.com/                   # 按网站分组的数据
    │   ├── memory.jsonl              # 内存监控时序数据
    │   ├── console.jsonl             # Console日志和异常
    │   ├── network.jsonl             # 网络请求生命周期
    │   ├── gc.jsonl                  # 垃圾回收事件
    │   ├── storage.jsonl             # 存储监控数据
    │   └── correlations.jsonl        # 跨指标关联分析
    └── another-site.com/
        └── ...                        # 其他网站的监控数据
```

## 核心数据类型详解

### 1. 内存监控数据 (memory.jsonl)

**采集频率**：每5秒一次

#### 基础内存指标
```json
{
  "type": "memory",
  "timestamp": "2025-08-16T14:30:25.123Z",
  "hostname": "example.com",
  "targetId": "1234ABCD",
  "sessionId": "5678EFGH",
  "url": "https://example.com/dashboard",
  "title": "Dashboard - Example",
  "event_id": "a1b2c3d4e5f6g7h8i9j0",  // 唯一标识，用于去重
  "memory": {
    "jsHeap": {
      "used": 52428800,     // JS堆使用量（字节）
      "total": 104857600    // JS堆总量（字节）
    },
    "domNodes": 1523,       // DOM节点数
    "listeners": 342,       // 事件监听器数量
    "documents": 3,         // 文档数
    "frames": 5            // 帧数
  },
  "performance": {
    "layoutCount": 45,      // 布局次数
    "layoutDuration": 123.5, // 布局总耗时（毫秒）
    "recalcStyleCount": 89,  // 样式重计算次数
    "recalcStyleDuration": 45.2, // 样式重计算耗时
    "scriptDuration": 567.8  // 脚本执行总时间
  }
}
```

#### 事件监听器详细分析
当监听器数量异常增长（>20个）时，会触发详细分析，在同一条记录中增加可选字段：

```json
{
  "type": "memory",
  "timestamp": "2025-08-16T14:30:25.123Z",
  "memory": {
    "listeners": 342  // 基础计数保持不变
  },
  "eventListenersAnalysis": {  // 可选扩展字段
    "summary": {
      "total": 342,
      "byTarget": {
        "document": 23,   // document对象上的监听器
        "window": 15,     // window对象上的监听器
        "elements": 304   // DOM元素上的监听器（估算）
      },
      "byType": {
        "click": 156,
        "scroll": 89,
        "resize": 45,
        "keydown": 32,
        "change": 20
      }
    },
    "growthDelta": 25,         // 相比上次检测的增长数
    "analysisTriggered": true, // 是否触发了详细分析
    "detailedSources": [       // 仅在triggerd时出现，定位具体泄漏源
      {
        "sourceFile": "https://example.com/js/ProductList.js",
        "lineNumber": 156,
        "functionName": "handleProductClick",
        "elementCount": 15,       // 该函数绑定到多少个元素
        "eventTypes": ["click"],
        "suspicion": "high"       // high/medium，根据elementCount判断
      },
      {
        "sourceFile": "https://example.com/js/charts.js",
        "lineNumber": 89,
        "functionName": "onDataUpdate", 
        "elementCount": 8,
        "eventTypes": ["change", "input"],
        "suspicion": "medium"
      }
    ]
  }
}
```

**监听器分析触发条件**：
- **轻量统计**：每次内存采集都会执行基础统计（byTarget, byType）
- **详细分析**：只在监听器增长>20个时异步执行，避免影响性能
- **来源定位**：通过DOMDebugger.getEventListeners获取函数名和代码位置
- **智能采样**：仅分析常见元素类型（按钮、表单、弹窗等），避免全页面扫描

**实际价值**：
- 从"监听器342个"提升到"ProductList.js:156的handleClick函数绑定到15个元素"
- 精确定位事件监听器泄漏的具体代码位置
- 发现重复绑定和未正确清理的监听器

#### 分析要点
- **内存泄漏检测**：JS堆持续增长，DOM节点数不断增加
- **监听器泄漏定位**：通过detailedSources找到具体的函数和文件位置
- **性能退化**：layoutDuration 和 scriptDuration 随时间增长
- **异常阈值**：
  - JS堆 > 500MB：严重内存问题
  - DOM节点 > 10000：DOM累积问题
  - 事件监听器 > 1000：可能存在未清理的监听器
  - elementCount > 10：高度可疑的监听器泄漏源

### 2. 网络请求数据 (network.jsonl)

**重要**：同一个请求会产生多个事件（start → complete/failed）

#### 2.1 请求开始事件
```json
{
  "type": "network_request_start",
  "timestamp": "2025-08-16T14:30:26.456Z",
  "requestId": "req_123456",
  "url": "https://api.example.com/data",
  "method": "POST",
  "contentLength": 102456,  // 上传大小（字节）
  "headers": {
    "Content-Type": "application/json",
    "Authorization": "Bearer...[truncated]"
  },
  "initiator": {
    "type": "script",
    "source": {
      "function": "fetchData",
      "url": "https://example.com/app.js",
      "line": 42
    }
  },
  "largeDataAlert": {  // 仅当上传 > 1MB 时出现
    "size": 5242880,
    "alert": "Large request body detected"
  },
  "event_id": "req123_start_unique_hash"
}
```

#### 2.2 请求完成事件（含调用栈增强）
```json
{
  "type": "network_request_complete",
  "timestamp": "2025-08-16T14:30:27.789Z",
  "requestId": "req_123456",
  "url": "https://api.example.com/export.json",
  "method": "GET",
  "status": 200,
  "mimeType": "application/json",
  "duration": 1.333,  // 请求耗时（秒）
  "encodedDataLength": 5242880,  // 响应大小（字节）
  "largeResponseAlert": {  // 仅当响应 > 1MB 时出现
    "size": 5242880,
    "alert": "Large response detected - potential 5.2MB JSON issue"
  },
  "detailedStack": {  // 🔥 高级功能：仅特定条件触发
    "enabled": true,
    "reason": "large_download",  // 触发原因
    "frames": [  // 完整JavaScript调用栈
      {
        "functionName": "ComponentA.fetchLargeData",
        "url": "https://example.com/components.js",
        "lineNumber": 156,
        "columnNumber": 15,
        "scriptId": "123"
      },
      {
        "functionName": "ComponentA.init",
        "url": "https://example.com/components.js", 
        "lineNumber": 42,
        "columnNumber": 8,
        "scriptId": "123"
      },
      {
        "functionName": "App.loadDashboard",
        "url": "https://example.com/app.js",
        "lineNumber": 789,
        "columnNumber": 4,
        "scriptId": "124"
      }
    ],
    "asyncFrames": [  // 异步调用栈
      {
        "functionName": "setTimeout callback",
        "url": "https://example.com/scheduler.js",
        "lineNumber": 23,
        "columnNumber": 12,
        "scriptId": "125"
      }
    ],
    "truncated": false,
    "collectionTime": "2025-08-16T14:30:27.800Z"
  },
  "event_id": "req123_complete_unique_hash"
}
```

#### 2.3 调用栈触发条件（detailedStack）

**注意**：detailedStack 只在以下条件出现，不要只看前几个请求！

| 触发原因 | 条件 | reason字段示例 |
|---------|------|--------------|
| 大上传 | postData > 100KB | `"large_upload"` |
| 大下载 | encodedDataLength > 100KB | `"large_download"` |
| 高频API | 同一端点调用 > 10次 | `"high_frequency_api_15"` |
| 重复资源 | 同一资源加载 > 3次且单次 > 10KB | `"repeated_resource_5"` |

#### 2.4 请求失败事件
```json
{
  "type": "network_request_failed",
  "timestamp": "2025-08-16T14:30:28.123Z",
  "requestId": "req_789012",
  "url": "https://api.example.com/timeout",
  "errorText": "net::ERR_CONNECTION_TIMED_OUT",
  "canceled": false,
  "event_id": "req789_failed_unique_hash"
}
```

#### 2.5 WebSocket监控事件

**重要**：WebSocket事件也记录在 network.jsonl 文件中，与HTTP请求数据共存。

**WebSocket连接创建**：
```json
{
  "type": "websocket_created",
  "timestamp": "2025-08-16T14:30:25.123Z",
  "requestId": "ws_connection_456",
  "url": "wss://example.com/live-data",
  "hostname": "example.com",
  "sessionId": "session_789",
  "event_id": "ws456_created_unique_hash"
}
```

**WebSocket文本消息帧**：
```json
{
  "type": "websocket_frame_sent",
  "timestamp": "2025-08-16T14:30:26.456Z",
  "requestId": "ws_connection_456",
  "url": "wss://example.com/live-data",
  "opcode": 1,  // 1=text, 2=binary, 8=close, 9=ping, 10=pong
  "payloadLength": 156,
  "payloadText": "{\"type\":\"subscribe\",\"channel\":\"prices\"}…",  // 截断至1024字符
  "frameStats": {
    "framesThisSecond": 12,  // 当前秒内的消息帧数
    "connectionAge": 45.6    // 连接存活时间（秒）
  },
  "hostname": "example.com",
  "sessionId": "session_789",
  "event_id": "ws456_frame_sent_unique_hash"
}
```

**WebSocket二进制消息帧**：
```json
{
  "type": "websocket_frame_received",
  "timestamp": "2025-08-16T14:30:27.789Z",
  "requestId": "ws_connection_456",
  "url": "wss://example.com/live-data",
  "opcode": 2,
  "payloadLength": 2048,
  "payloadType": "binary",  // 二进制消息仅记录类型和长度，不存储内容
  "frameStats": {
    "framesThisSecond": 8,
    "connectionAge": 46.3
  },
  "hostname": "example.com",
  "sessionId": "session_789",
  "event_id": "ws456_frame_recv_unique_hash"
}
```

**WebSocket错误事件**：
```json
{
  "type": "websocket_frame_error",
  "timestamp": "2025-08-16T14:30:28.123Z",
  "requestId": "ws_connection_456",
  "url": "wss://example.com/live-data",
  "errorMessage": "Frame parsing failed: invalid UTF-8 sequence",
  "hostname": "example.com",
  "sessionId": "session_789",
  "event_id": "ws456_frame_error_unique_hash"
}
```

**WebSocket连接关闭**：
```json
{
  "type": "websocket_closed",
  "timestamp": "2025-08-16T14:30:29.456Z",
  "requestId": "ws_connection_456",
  "url": "wss://example.com/live-data",
  "hostname": "example.com",
  "sessionId": "session_789",
  "event_id": "ws456_closed_unique_hash"
}
```

**🔍 WebSocket数据分析要点**：

1. **连接跟踪**：通过 `requestId` 关联同一WebSocket的全生命周期事件
2. **消息频率分析**：`frameStats.framesThisSecond` 可发现"消息风暴"问题
3. **连接稳定性**：分析 `websocket_closed` 和 `websocket_frame_error` 频率
4. **数据传输量**：通过 `payloadLength` 统计数据传输量
5. **性能影响**：高频消息可能导致渲染性能问题

**典型问题场景**：
- **高频消息**：`framesThisSecond > 50` 可能导致CPU占用过高
- **连接泄漏**：只有 `websocket_created` 没有 `websocket_closed`
- **错误重连**：短时间内多次 `websocket_created` + `websocket_frame_error`
- **数据编码问题**：`websocket_frame_error` 中的 "invalid UTF-8" 错误

### 3. Console日志数据 (console.jsonl)

#### 3.1 Console消息
```json
{
  "type": "console",
  "timestamp": "2025-08-16T14:30:29.456Z",
  "hostname": "example.com",
  "level": "error",  // log, warn, error, info, debug
  "message": "TypeError: Cannot read property 'value' of null",
  "source": {
    "url": "https://example.com/app.js",
    "line": 234,
    "column": 15
  },
  "stackTrace": [  // 错误堆栈（仅error级别）
    {
      "functionName": "handleSubmit",
      "url": "https://example.com/form.js",
      "lineNumber": 45,
      "columnNumber": 8
    }
  ],
  "event_id": "console_error_unique_hash"
}
```

#### 3.2 JavaScript异常
```json
{
  "type": "exception",
  "timestamp": "2025-08-16T14:30:30.789Z",
  "hostname": "example.com",
  "message": "Uncaught ReferenceError: undefinedVariable is not defined",
  "source": {
    "url": "https://example.com/utils.js",
    "line": 567,
    "column": 23
  },
  "event_id": "exception_unique_hash"
}
```

### 4. 垃圾回收数据 (gc.jsonl)

```json
{
  "type": "gc",
  "timestamp": "2025-08-16T14:30:31.123Z",
  "hostname": "example.com",
  "targetId": "1234ABCD",
  "heapBefore": 104857600,  // GC前堆大小（字节）
  "heapAfter": 52428800,    // GC后堆大小
  "heapDelta": -52428800,   // 释放的内存量
  "gcType": "major",        // major/minor
  "duration": 45.6          // GC耗时（毫秒，如果有）
}
```

### 5. 存储监控数据 (storage.jsonl)

#### 5.1 存储配额监控（自动）
```json
{
  "type": "storage_quota",
  "timestamp": "2025-08-16T14:30:32.456Z",
  "hostname": "example.com",
  "targetId": "1234ABCD",
  "quota": 137438953472,     // 总配额（字节，约128GB）
  "usage": 524288000,         // 已使用（字节，约500MB）
  "usagePercent": 0.38,       // 使用百分比
  "source": "browser"         // browser/page（数据来源）
}
```

#### 5.2 DOMStorage事件（自动）
```json
{
  "type": "domstorage_event",
  "timestamp": "2025-08-16T14:30:33.789Z",
  "hostname": "example.com",
  "targetId": "1234ABCD",
  "origin": "https://example.com",
  "storageType": "localStorage",  // localStorage/sessionStorage
  "action": "setItem",             // setItem/removeItem/clear
  "key": "user_preferences",
  "newValue": "{\"theme\":\"dark\",\"language\":\"zh-CN\"}",
  "oldValue": "{\"theme\":\"light\",\"language\":\"en-US\"}"
}
```

#### 5.3 DOMStorage快照（手动触发）🔥

**重要**：这是通过 `browserfairy --snapshot-storage-once` 手动触发的完整存储快照

```json
{
  "type": "domstorage_snapshot",
  "timestamp": "2025-08-16T14:30:34.123Z",
  "hostname": "example.com",
  "targetId": "1234ABCD",
  "origin": "https://example.com",
  "data": {
    "estimate": {
      "quota": 137438953472,
      "usage": 524288
    },
    "local": [  // localStorage完整内容
      {
        "key": "user_preferences",
        "value": "{\"theme\":\"dark\",\"language\":\"zh-CN\",\"notifications\":true}"
      },
      {
        "key": "auth_token",
        "value": "eyJhbGciOiJSUzI1NiIsInR5cCI6Ik...[truncated]"  // 超长值被截断
      },
      {
        "key": "cached_data",
        "value": "[{\"id\":1,\"name\":\"Product A\",\"price\":99.99},{\"id\":2,\"name\":\"Product B\",\"price\":149.99}]"
      }
    ],
    "session": [  // sessionStorage完整内容
      {
        "key": "temp_cart",
        "value": "[{\"productId\":1,\"quantity\":2},{\"productId\":3,\"quantity\":1}]"
      },
      {
        "key": "form_draft",
        "value": "{\"title\":\"未完成的文章\",\"content\":\"这是一个草稿...\"}"
      }
    ]
  }
}
```

**快照使用场景**：
- 诊断登录/认证问题（检查auth_token）
- 分析缓存数据量（检查cached_data大小）
- 调试表单数据丢失（检查form_draft）
- 了解用户偏好设置（检查user_preferences）

### 6. 关联分析数据 (correlations.jsonl)

**智能关联**：3秒时间窗口内的相关事件

```json
{
  "type": "correlation",
  "timestamp": "2025-08-16T14:30:35.456Z",
  "hostname": "example.com",
  "timeWindow": {
    "start": "2025-08-16T14:30:32.456Z",
    "end": "2025-08-16T14:30:35.456Z"
  },
  "events": [
    {
      "type": "memory",
      "timestamp": "2025-08-16T14:30:32.500Z",
      "jsHeapDelta": 52428800,  // 内存增加50MB
      "domNodesDelta": 500
    },
    {
      "type": "network_complete",
      "timestamp": "2025-08-16T14:30:33.000Z",
      "url": "https://api.example.com/large-data.json",
      "size": 5242880  // 5MB响应
    },
    {
      "type": "console_error",
      "timestamp": "2025-08-16T14:30:34.000Z",
      "message": "Maximum call stack size exceeded"
    }
  ],
  "analysis": {
    "pattern": "large_data_processing_issue",
    "confidence": 0.85,
    "description": "大数据响应后内存激增并出现栈溢出"
  }
}
```

## 高级功能分析

### 网络请求调用栈分析

**如何找到调用栈数据**：

1. **不要只看文件开头**！调用栈数据通常在后面
2. 搜索含有 `"detailedStack"` 字段的记录
3. 查看 `reason` 字段了解触发原因

**分析示例**：
```bash
# 查找所有包含详细调用栈的请求
grep '"detailedStack"' network.jsonl | jq '.detailedStack.reason' | sort | uniq -c

# 输出示例：
#   15 "high_frequency_api_52"
#    8 "large_download"
#    3 "repeated_resource_6"
```

**调用栈解读**：
- `frames`：从内到外的调用链（最内层函数在前）
- `asyncFrames`：异步边界（Promise、setTimeout等）
- `lineNumber/columnNumber`：精确代码位置

### DOMStorage快照分析

**获取快照**：
```bash
# 手动触发所有页面的存储快照
browserfairy --snapshot-storage-once

# 仅特定网站
browserfairy --snapshot-storage-once --snapshot-hostname example.com

# 限制值长度（隐私保护）
browserfairy --snapshot-storage-once --snapshot-maxlen 100
```

**分析要点**：
1. **存储大小**：检查 usage 是否接近 quota
2. **数据结构**：分析存储的JSON结构是否合理
3. **敏感信息**：注意token、密码等敏感数据
4. **缓存策略**：评估缓存数据的必要性和时效性

### 事件去重机制

每个事件都有唯一的 `event_id`，用于去重和关联：

```python
# Python去重示例
import json
from collections import defaultdict

seen_events = set()
unique_events = []

with open('memory.jsonl', 'r') as f:
    for line in f:
        event = json.loads(line)
        event_id = event.get('event_id')
        if event_id and event_id not in seen_events:
            seen_events.add(event_id)
            unique_events.append(event)

print(f"总事件数: {len(lines)}, 去重后: {len(unique_events)}")
```

## 典型问题诊断示例

### 示例1：内存泄漏诊断

```python
import json
import matplotlib.pyplot as plt

# 读取内存数据
timestamps = []
heap_sizes = []

with open('example.com/memory.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        timestamps.append(data['timestamp'])
        heap_sizes.append(data['memory']['jsHeap']['used'] / 1024 / 1024)  # 转MB

# 绘制趋势图
plt.plot(timestamps, heap_sizes)
plt.xlabel('Time')
plt.ylabel('JS Heap (MB)')
plt.title('Memory Usage Trend')
plt.xticks(rotation=45)
plt.show()

# 诊断：如果曲线持续上升，存在内存泄漏
```

### 示例2：性能瓶颈定位

```python
# 查找大请求的发起者
import json

with open('example.com/network.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if 'detailedStack' in data and data['detailedStack']['enabled']:
            print(f"\n大请求: {data['url']}")
            print(f"原因: {data['detailedStack']['reason']}")
            print("调用链:")
            for frame in data['detailedStack']['frames'][:3]:  # 显示前3层
                print(f"  - {frame['functionName']} ({frame['url']}:{frame['lineNumber']})")
```

### 示例3：事件监听器泄漏诊断

```python
# 分析事件监听器泄漏问题
import json

def analyze_listener_leaks(memory_file):
    """分析事件监听器泄漏源"""
    
    with open(memory_file, 'r') as f:
        for line in f:
            data = json.loads(line)
            
            # 查找包含详细分析的记录
            if 'eventListenersAnalysis' in data:
                analysis = data['eventListenersAnalysis']
                
                print(f"\n时间: {data['timestamp']}")
                print(f"监听器总数: {analysis['summary']['total']}")
                print(f"增长数量: {analysis['growthDelta']}")
                
                # 显示分布统计
                by_target = analysis['summary']['byTarget']
                print(f"分布: document({by_target['document']}) + window({by_target['window']}) + elements({by_target['elements']})")
                
                # 显示详细泄漏源（如果触发了详细分析）
                if analysis.get('analysisTriggered') and 'detailedSources' in analysis:
                    print("🔥 发现可疑监听器泄漏源:")
                    for source in analysis['detailedSources']:
                        suspicion = "🚨" if source['suspicion'] == 'high' else "⚠️"
                        print(f"  {suspicion} {source['functionName']}")
                        print(f"     文件: {source['sourceFile']}:{source['lineNumber']}")
                        print(f"     绑定元素: {source['elementCount']} 个")
                        print(f"     事件类型: {', '.join(source['eventTypes'])}")

# 使用示例
analyze_listener_leaks('example.com/memory.jsonl')

# 输出示例:
# 时间: 2025-08-16T14:30:25.123Z
# 监听器总数: 342
# 增长数量: 25
# 分布: document(23) + window(15) + elements(304)
# 🔥 发现可疑监听器泄漏源:
#   🚨 handleProductClick
#      文件: https://example.com/js/ProductList.js:156
#      绑定元素: 15 个
#      事件类型: click
#   ⚠️ onDataUpdate
#      文件: https://example.com/js/charts.js:89
#      绑定元素: 8 个
#      事件类型: change, input
```

### 示例4：错误模式分析

```python
# 统计最频繁的错误
from collections import Counter

errors = []
with open('example.com/console.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if data.get('level') == 'error':
            errors.append(data['message'][:50])  # 取前50字符

error_counts = Counter(errors)
print("Top 10 错误:")
for error, count in error_counts.most_common(10):
    print(f"{count:4d} 次: {error}")
```

## 数据分析最佳实践

### 1. 完整性检查
```bash
# 确保读取完整文件
tail -n 100 network.jsonl | grep detailedStack
# 如果有结果，说明重要数据在文件后部
```

### 2. 时间序列分析
- 使用 timestamp 字段进行时序分析
- 注意时区（默认UTC）
- 关注突变点和趋势

### 3. 跨文件关联
```python
# 关联内存峰值和网络请求
memory_spike_time = "2025-08-16T14:30:32.500Z"

# 查找同时期的网络请求
with open('network.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if abs(parse_time(data['timestamp']) - parse_time(memory_spike_time)) < 5:
            print(f"相关请求: {data['url']}")
```

### 4. 自动化分析脚本

创建可重用的分析脚本：

```python
#!/usr/bin/env python3
"""BrowserFairy数据分析工具"""

import json
import sys
from pathlib import Path

def analyze_session(session_dir):
    """分析一个监控会话"""
    session_path = Path(session_dir)
    
    # 统计各类事件
    for site_dir in session_path.glob('*/'):
        if site_dir.is_dir():
            print(f"\n分析网站: {site_dir.name}")
            
            # 内存分析
            memory_file = site_dir / 'memory.jsonl'
            if memory_file.exists():
                analyze_memory(memory_file)
            
            # 网络分析
            network_file = site_dir / 'network.jsonl'
            if network_file.exists():
                analyze_network(network_file)
            
            # 存储快照分析
            storage_file = site_dir / 'storage.jsonl'
            if storage_file.exists():
                analyze_storage(storage_file)

def analyze_memory(file_path):
    """分析内存数据"""
    listener_analyses = 0
    high_suspicion_sources = 0
    
    with open(file_path, 'r') as f:
        lines = f.readlines()
        if lines:
            first = json.loads(lines[0])
            last = json.loads(lines[-1])
            
            initial_heap = first['memory']['jsHeap']['used'] / 1024 / 1024
            final_heap = last['memory']['jsHeap']['used'] / 1024 / 1024
            
            # 分析监听器详细分析
            for line in lines:
                data = json.loads(line)
                if 'eventListenersAnalysis' in data:
                    listener_analyses += 1
                    if 'detailedSources' in data['eventListenersAnalysis']:
                        for source in data['eventListenersAnalysis']['detailedSources']:
                            if source.get('suspicion') == 'high':
                                high_suspicion_sources += 1
            
            print(f"  内存: {initial_heap:.1f}MB → {final_heap:.1f}MB (增长{final_heap-initial_heap:.1f}MB)")
            if listener_analyses > 0:
                print(f"  监听器分析: {listener_analyses}次, {high_suspicion_sources}个高可疑源")

def analyze_network(file_path):
    """分析网络数据"""
    detailed_stacks = 0
    large_requests = 0
    
    with open(file_path, 'r') as f:
        for line in f:
            data = json.loads(line)
            if 'detailedStack' in data:
                detailed_stacks += 1
            if 'largeResponseAlert' in data or 'largeDataAlert' in data:
                large_requests += 1
    
    print(f"  网络: {large_requests}个大请求, {detailed_stacks}个详细调用栈")

def analyze_storage(file_path):
    """分析存储数据"""
    snapshots = 0
    with open(file_path, 'r') as f:
        for line in f:
            data = json.loads(line)
            if data['type'] == 'domstorage_snapshot':
                snapshots += 1
                # 分析快照内容
                if 'data' in data:
                    local_items = len(data['data'].get('local', []))
                    session_items = len(data['data'].get('session', []))
                    print(f"  存储快照: localStorage {local_items} 项, sessionStorage {session_items} 项")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python analyze.py <session_directory>")
        sys.exit(1)
    
    analyze_session(sys.argv[1])
```

## 总结

BrowserFairy 的监控数据包含丰富的性能和行为信息，但很多高级功能（如调用栈、存储快照）**不在文件开头**，需要：

1. **完整读取文件**，不要只看前几行
2. **理解触发条件**，知道什么情况下会产生特殊数据
3. **跨文件关联**，结合多个数据源进行综合分析
4. **使用自动化工具**，编写脚本批量处理

通过充分利用这些数据，可以精确定位性能问题、内存泄漏、异常模式等Web应用的深层问题。
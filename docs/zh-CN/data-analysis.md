# 数据分析指南

## 概述

BrowserFairy生成的监控数据采用**JSONL格式**（JSON Lines），每行一个JSON对象，便于流式处理和AI分析。

## 数据文件结构

```
session_2025-01-20_143022/          # 监控会话
├── overview.json                   # 会话概览
└── example.com/                    # 按网站分组
    ├── memory.jsonl                # 内存监控
    ├── console.jsonl               # 控制台日志
    ├── network.jsonl               # 网络请求
    ├── longtask.jsonl              # 长任务检测
    ├── gc.jsonl                    # 垃圾回收
    ├── storage.jsonl               # 存储监控
    └── correlations.jsonl          # 关联分析
```

## 核心数据类型

### 1. 内存监控 (memory.jsonl)

**基础指标**（每5秒采集）：
```json
{
  "type": "memory",
  "timestamp": "2025-01-20T14:30:25.123Z",
  "hostname": "example.com",
  "event_id": "unique_hash_id",
  "memory": {
    "jsHeap": {
      "used": 52428800,      // JS堆使用（字节）
      "total": 104857600     // JS堆总量
    },
    "domNodes": 1523,        // DOM节点数
    "listeners": 342         // 事件监听器数
  }
}
```

**高级：事件监听器泄漏检测**

当监听器异常增长时，会自动分析泄漏源：
```json
{
  "eventListenersAnalysis": {
    "detailedSources": [
      {
        "sourceFile": "https://example.com/js/ProductList.js",
        "lineNumber": 156,
        "functionName": "handleProductClick",
        "elementCount": 15,
        "suspicion": "high"  // 泄漏可能性：high/medium
      }
    ]
  }
}
```

### 2. 控制台日志 (console.jsonl)

**错误和异常**：
```json
{
  "type": "console",
  "level": "error",
  "message": "TypeError: Cannot read property 'value' of null",
  "source": {
    "url": "https://example.com/app.js",
    "line": 234,
    "column": 15
  },
  "stackTrace": [...]
}
```

### 3. 网络请求 (network.jsonl)

**请求生命周期**：
- `network_request_start` - 请求开始
- `network_request_complete` - 请求完成
- `network_request_failed` - 请求失败

**高级：调用栈追踪**

对于大请求或高频请求，自动记录JavaScript调用栈：
```json
{
  "type": "network_request_complete",
  "url": "https://api.example.com/data",
  "encodedDataLength": 5242880,  // 5MB响应
  "detailedStack": {
    "reason": "large_download",
    "frames": [
      {
        "functionName": "Dashboard.fetchData",
        "url": "https://example.com/app.js",
        "lineNumber": 89
      }
    ]
  }
}
```

触发条件：
- 大上传：> 100KB
- 大下载：> 100KB  
- 高频API：同一端点 > 10次
- 重复资源：> 3次且单次 > 10KB

### 4. WebSocket监控

WebSocket事件也记录在network.jsonl中：
```json
{
  "type": "websocket_frame_sent",
  "url": "wss://example.com/live",
  "payloadLength": 156,
  "frameStats": {
    "framesThisSecond": 12,  // 消息频率
    "connectionAge": 45.6     // 连接时长
  }
}
```

### 5. 长任务检测 (longtask.jsonl)

检测阻塞主线程的JavaScript执行（>50ms）：
```json
{
  "type": "longtask",
  "duration": 156.7,  // 毫秒
  "stack": {
    "frames": [
      {
        "functionName": "processLargeDataset",
        "url": "https://example.com/processor.js",
        "lineNumber": 234
      }
    ]
  }
}
```

### 6. 存储监控 (storage.jsonl)

**DOMStorage快照**（手动触发）：
```bash
browserfairy --snapshot-storage-once
```

生成完整的localStorage/sessionStorage快照：
```json
{
  "type": "domstorage_snapshot",
  "data": {
    "local": [
      {"key": "user_token", "value": "..."},
      {"key": "preferences", "value": "..."}
    ],
    "session": [
      {"key": "temp_data", "value": "..."}
    ]
  }
}
```

## 快速分析示例

### 1. 查找内存泄漏

```python
import json

# 分析内存趋势
with open('memory.jsonl', 'r') as f:
    data = [json.loads(line) for line in f]
    
initial = data[0]['memory']['jsHeap']['used']
final = data[-1]['memory']['jsHeap']['used']
leak = (final - initial) / 1024 / 1024

print(f"内存增长: {leak:.1f} MB")

# 查找监听器泄漏源
for item in data:
    if 'eventListenersAnalysis' in item:
        sources = item['eventListenersAnalysis'].get('detailedSources', [])
        for source in sources:
            if source['suspicion'] == 'high':
                print(f"泄漏源: {source['sourceFile']}:{source['lineNumber']}")
```

### 2. 分析错误模式

```python
from collections import Counter

# 统计最频繁的错误
errors = []
with open('console.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if data.get('level') == 'error':
            errors.append(data['message'][:50])

for error, count in Counter(errors).most_common(5):
    print(f"{count}次: {error}")
```

### 3. 找出性能瓶颈

```python
# 查找大请求的发起者
with open('network.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if 'detailedStack' in data:
            print(f"大请求: {data['url']}")
            print(f"原因: {data['detailedStack']['reason']}")
            frame = data['detailedStack']['frames'][0]
            print(f"调用者: {frame['functionName']} at line {frame['lineNumber']}")
```

## AI友好的数据特性

### 1. 事件ID去重

每个事件都有唯一的`event_id`，便于去重：
```python
seen = set()
unique_events = []
for event in events:
    if event['event_id'] not in seen:
        seen.add(event['event_id'])
        unique_events.append(event)
```

### 2. 时间窗口关联

correlations.jsonl包含15秒窗口内的相关事件：
```json
{
  "type": "correlation",
  "events": [
    {"type": "memory", "jsHeapDelta": 52428800},
    {"type": "network_complete", "size": 5242880},
    {"type": "console_error", "message": "Out of memory"}
  ],
  "analysis": {
    "pattern": "large_data_processing_issue",
    "description": "大数据响应后内存激增并出错"
  }
}
```

### 3. 输出过滤

使用`--output`参数控制数据量：
- `errors-only`: 仅错误（最小）
- `ai-debug`: AI调试常用
- `performance`: 性能相关
- `all`: 完整数据（默认）

## 进阶分析

### 完整分析脚本模板

```python
#!/usr/bin/env python3
"""BrowserFairy数据分析工具"""

import json
from pathlib import Path

def analyze_session(session_dir):
    """分析监控会话"""
    session_path = Path(session_dir)
    
    for site_dir in session_path.glob('*/'):
        if not site_dir.is_dir():
            continue
            
        print(f"\n分析网站: {site_dir.name}")
        
        # 内存分析
        memory_file = site_dir / 'memory.jsonl'
        if memory_file.exists():
            analyze_memory(memory_file)
        
        # 错误分析
        console_file = site_dir / 'console.jsonl'
        if console_file.exists():
            analyze_errors(console_file)

def analyze_memory(file_path):
    """分析内存数据"""
    with open(file_path, 'r') as f:
        lines = f.readlines()
        if not lines:
            return
            
        first = json.loads(lines[0])
        last = json.loads(lines[-1])
        
        initial_heap = first['memory']['jsHeap']['used'] / 1024 / 1024
        final_heap = last['memory']['jsHeap']['used'] / 1024 / 1024
        
        print(f"  内存: {initial_heap:.1f}MB → {final_heap:.1f}MB")
        
        # 检查监听器泄漏
        for line in lines:
            data = json.loads(line)
            analysis = data.get('eventListenersAnalysis', {})
            sources = analysis.get('detailedSources', [])
            for source in sources:
                if source.get('suspicion') == 'high':
                    print(f"  ⚠️  泄漏源: {source['functionName']} at {source['sourceFile']}:{source['lineNumber']}")

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python analyze.py <session_directory>")
        sys.exit(1)
    analyze_session(sys.argv[1])
```

## 最佳实践

1. **完整读取文件** - 重要数据可能在文件末尾
2. **关注异常模式** - 突变点比绝对值更重要
3. **跨文件关联** - 结合多个数据源综合分析
4. **使用自动化** - 编写脚本批量处理

## 深入学习

完整的数据格式说明和更多分析示例，请参考：
- [完整数据格式文档](https://github.com/shanrichard/browserfairy/blob/main/DATA_ANALYSIS_GUIDE.md)
- [API参考](./commands.md#data-format)
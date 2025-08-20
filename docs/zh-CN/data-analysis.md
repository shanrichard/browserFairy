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
    ├── heap_sampling.jsonl         # 内存分配采样 🆕
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
  "type": "exception",
  "message": "TypeError: Cannot read property 'value' of null",
  "source": {
    "url": "https://example.com/bundle.min.js",
    "line": 1,
    "column": 45678
  },
  "stackTrace": [
    {
      "function": "handleSubmit",
      "url": "https://example.com/bundle.min.js",
      "line": 1,
      "column": 45678,
      "scriptId": "123",
      "lineNumber": 1,
      "columnNumber": 45678,
      "original": {  // 🆕 Source Map解析结果（需启用--enable-source-map）
        "file": "src/components/Form.jsx",
        "line": 42,
        "column": 15,
        "name": "handleSubmit"
      }
    }
  ]
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

### 7. 内存分配采样 (heap_sampling.jsonl) 🆕

**HeapProfiler采样分析**（每60秒采集）：

这是最新加入的功能，专门用于精确定位内存泄漏源头函数。

```json
{
  "type": "heap_sampling",
  "timestamp": "2025-01-20T14:30:25.123Z",
  "hostname": "example.com",
  "targetId": "target_123",
  "sessionId": "session_456",
  "sampling_config": {
    "sampling_interval": 65536,    // 64KB采样间隔
    "duration_ms": 45000           // 采样持续时间
  },
  "profile_summary": {
    "total_size": 104857600,       // 总分配量（字节）
    "total_samples": 250,          // 采样次数
    "node_count": 85,              // 调用栈节点数
    "max_allocation_size": 8388608 // 最大单次分配
  },
  "top_allocators": [              // 内存分配热点函数（Top 10）
    {
      "function_name": "allocateArray",
      "script_url": "https://example.com/DataProcessor.js",
      "line_number": 89,
      "column_number": 23,
      "self_size": 52428800,       // 该函数分配的内存（50MB）
      "sample_count": 85,          // 采样次数
      "allocation_percentage": 50.0 // 占总分配的百分比
    },
    {
      "function_name": "processLargeDataset",
      "script_url": "https://example.com/utils.js", 
      "line_number": 156,
      "self_size": 20971520,       // 20MB
      "sample_count": 32,
      "allocation_percentage": 20.0
    }
  ],
  "event_id": "heap_sample_unique_id"
}
```

**🎯 使用价值**：
- **精确定位泄漏源**：定位到具体函数和行号
- **量化分配影响**：知道每个函数分配了多少内存
- **优先级排序**：按分配量排序，优先修复影响最大的函数
- **趋势分析**：结合时间序列数据，发现分配模式

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

### 2. 分析错误模式（含Source Map）

```python
from collections import Counter

# 统计最频繁的错误（使用Source Map定位源代码）
errors = []
with open('console.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'exception':
            # 优先使用Source Map解析后的位置
            if data.get('stackTrace'):
                frame = data['stackTrace'][0]
                if 'original' in frame:
                    # 有Source Map数据，使用原始位置
                    location = f"{frame['original']['file']}:{frame['original']['line']}"
                    func = frame['original'].get('name', frame['function'])
                else:
                    # 没有Source Map，使用压缩代码位置
                    location = f"{frame['url']}:{frame['line']}"
                    func = frame['function']
                
                error_info = f"{data['message'][:30]} at {func} ({location})"
                errors.append(error_info)

# 显示错误频率
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

### 4. Source Map数据使用 🆕

```python
# 分析启用Source Map后的错误数据
def analyze_with_source_map(filename='console.jsonl'):
    errors_by_source = {}
    
    with open(filename, 'r') as f:
        for line in f:
            data = json.loads(line)
            if data.get('type') == 'exception' and data.get('stackTrace'):
                for frame in data['stackTrace']:
                    if 'original' in frame:
                        # 使用Source Map解析后的数据
                        source_file = frame['original']['file']
                        source_line = frame['original']['line']
                        func_name = frame['original'].get('name', 'anonymous')
                        
                        key = f"{source_file}:{source_line}"
                        if key not in errors_by_source:
                            errors_by_source[key] = {
                                'file': source_file,
                                'line': source_line,
                                'function': func_name,
                                'errors': []
                            }
                        errors_by_source[key]['errors'].append(data['message'])
    
    # 按错误数量排序
    sorted_errors = sorted(errors_by_source.items(), 
                          key=lambda x: len(x[1]['errors']), 
                          reverse=True)
    
    print("源代码错误热点（按错误频率排序）：")
    for key, info in sorted_errors[:10]:
        print(f"\n{info['file']}:{info['line']} ({info['function']})")
        print(f"  错误次数: {len(info['errors'])}")
        print(f"  示例错误: {info['errors'][0][:50]}")
```

**Source Map数据的价值**：
- **精确定位**：直接看到`Form.jsx:42`而不是`bundle.min.js:1:45678`
- **函数名恢复**：看到原始函数名而不是混淆后的名称
- **AI友好**：AI可以直接理解源代码位置，给出精确修复建议
- **调试效率**：减少从压缩代码反推源码的时间

### 5. 分析内存分配热点

```python
# 分析HeapProfiler采样数据，找出内存分配热点
with open('heap_sampling.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'heap_sampling':
            print(f"采样时间: {data['timestamp']}")
            print(f"总分配量: {data['profile_summary']['total_size'] / 1024 / 1024:.1f} MB")
            print("内存分配热点函数:")
            
            for allocator in data['top_allocators'][:3]:  # 显示Top 3
                size_mb = allocator['self_size'] / 1024 / 1024
                func_info = f"{allocator['function_name']}() - {allocator['script_url'].split('/')[-1]}:{allocator['line_number']}"
                print(f"  {size_mb:.1f}MB ({allocator['allocation_percentage']:.1f}%): {func_info}")
            print()
```

**输出示例**：
```
采样时间: 2025-01-20T14:30:25.123Z
总分配量: 100.0 MB
内存分配热点函数:
  50.0MB (50.0%): allocateArray() - DataProcessor.js:89
  20.0MB (20.0%): processLargeDataset() - utils.js:156  
  15.0MB (15.0%): createBuffers() - renderer.js:234
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

def analyze_heap_sampling(file_path):
    """分析内存采样数据"""
    with open(file_path, 'r') as f:
        lines = f.readlines()
        if not lines:
            return
            
        print("  内存分配热点:")
        for line in lines:
            data = json.loads(line)
            if data.get('type') == 'heap_sampling':
                top_allocators = data.get('top_allocators', [])[:3]  # 显示top 3
                for allocator in top_allocators:
                    size_mb = allocator.get('self_size', 0) / 1024 / 1024
                    percentage = allocator.get('allocation_percentage', 0)
                    print(f"    {allocator.get('function_name', 'unknown')} - {size_mb:.1f}MB ({percentage:.1f}%)")
                    print(f"      文件: {allocator.get('script_url', '')}")

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
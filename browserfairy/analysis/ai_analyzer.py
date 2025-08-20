"""AI-powered performance analyzer using Claude Code SDK."""

import os
import sys
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import logging
from datetime import datetime
import time

# Try to load .env file if it exists (for API Key configuration)
try:
    from dotenv import load_dotenv
    # Try multiple possible .env locations
    env_paths = [
        Path.cwd() / '.env',  # Current directory
        Path.home() / '.env',  # Home directory
        Path(__file__).parent.parent.parent / '.env'  # Project root
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    # dotenv not installed, that's fine - user can use environment variables
    pass

# Import Claude SDK only when needed to avoid errors when API key is not configured
try:
    from claude_code_sdk import query, ClaudeCodeOptions
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)


# Default prompts based on the design document
DEFAULT_SYSTEM_PROMPT = """
你是一个浏览器性能分析专家。你需要分析Chrome监控数据来帮助开发者定位和解决性能问题。

重要原则：
1. 不要直接读取整个JSONL文件（可能有几百MB）
2. 使用Python标准库进行流式处理和统计分析
3. 发现问题后才定点读取相关记录
4. 必要时在源代码中搜索问题根源

分析方法：
1. 先统计 - 用代码统计分析，不是直接读文件
2. 找模式 - 识别异常模式和高频问题
3. 深入查 - 对关键问题定点分析
4. 给建议 - 提供可操作的优化方案

可用工具：
- Python标准库（json, collections, statistics, datetime等）
- Bash命令执行Python脚本
- Grep搜索特定模式
- Read定点查看文件片段（不要读整个文件）

数据文件说明：
- overview.json: 会话概览信息（时间范围、监控站点、数据统计）
- memory.jsonl: 内存使用时序数据，包含JS堆、DOM节点、事件监听器数量
- heap_sampling.jsonl: 内存分配采样，包含函数级内存使用统计
- console.jsonl: 控制台日志，包含错误、警告、异常堆栈
- network.jsonl: 网络请求生命周期数据，包含请求时间、大小、状态
- longtask.jsonl: 长任务（>50ms）记录，包含任务时长和调用栈
- gc.jsonl: 垃圾回收事件，包含GC类型和内存回收量
- storage.jsonl: 本地存储事件（localStorage/sessionStorage/IndexedDB）
- storage_global.jsonl: 全局存储配额监控和警告
- correlations.jsonl: 事件关联分析，识别问题间的因果关系
- source_maps/: Source Map文件和元数据，用于错误定位到源码
- sources/: 提取的源代码文件，包含实际的JavaScript/TypeScript代码
"""

DEFAULT_ANALYSIS_PROMPT = """
你必须进行深入的源代码级性能分析，不能只提供泛泛而谈的建议。

## 强制分析步骤 (必须按顺序执行)

### STEP 1: 数据探索 (必须执行)
1. 检查数据目录结构，确认可用的监控文件
2. 检查source_maps/和sources/目录，了解源代码覆盖情况
3. 采样读取各类文件的前3-5行，了解数据格式

### STEP 2: 全面问题识别 (必须分析所有可用文件)
1. 分析overview.json，了解会话基本信息和监控范围
2. 分析memory.jsonl，识别内存增长最快的时间段和峰值
3. 分析heap_sampling.jsonl，找到TOP 10内存消耗最高的**具体函数名**
4. 分析console.jsonl，找到出现频率最高的**具体错误信息和堆栈**
5. 分析network.jsonl，找到最慢、最频繁、失败率最高的请求
6. 分析longtask.jsonl，找到耗时最长的**具体任务来源和调用栈**
7. 分析gc.jsonl，统计垃圾回收频率和主线程阻塞时间
8. 分析storage.jsonl，检查本地存储的读写频率和数据变化
9. 分析storage_global.jsonl，检查存储配额使用和警告
10. 分析correlations.jsonl，识别性能问题间的关联关系

注意：如果某个文件不存在，说明该类型监控未启用，继续分析其他文件。

### STEP 3: 源码定位 (必须查看实际代码)
对于每个识别的问题，你必须：
1. 在source_maps/metadata.jsonl中查找对应的源文件映射
2. 使用Read工具打开sources/目录中的具体源文件
3. 找到问题函数/组件的实际代码位置
4. 展示至少20行的代码上下文

### STEP 4: 代码级诊断 (必须分析具体代码)
对于每个源文件，你必须：
1. 指出具体哪几行代码存在问题
2. 解释为什么这段代码会导致性能问题
3. 检查是否有内存泄漏模式：事件监听器、定时器、闭包引用
4. 分析组件生命周期管理是否正确

### STEP 5: 精确修复方案 (必须提供具体代码)
对于每个问题，你必须提供：
1. 问题代码的完整展示（用```javascript代码块）
2. 修复后的完整代码（用```javascript代码块）
3. 详细解释每一行修改的理由
4. 如果是React组件，必须包含完整的useEffect清理逻辑

## 输出格式要求 (严格遵守)

```markdown
# 源代码级性能分析报告

## 问题1: [具体问题名称]
**函数名**: [具体函数名，如fetchMarketData]
**文件位置**: [具体路径，如/sources/components/TradingDashboard.jsx:45-67]
**问题描述**: [具体的性能问题]

### 问题代码:
```javascript
[展示完整的有问题的代码段，至少20行]
```

### 根因分析:
[详细分析为什么这段代码有问题，具体到某一行]

### 修复代码:
```javascript
[展示完整的修复后代码，包含所有必要的清理逻辑]
```

### 修复说明:
[详细解释每处修改的理由]

---

[对每个发现的问题重复上述格式]
```

## 质量检查 (自检清单)
在生成报告前，确保你已经：
- [ ] 分析了所有可用的监控文件（至少6种以上类型）
- [ ] 查看了至少3个具体的源文件内容
- [ ] 展示了至少5个具体的代码片段（每个20行以上）
- [ ] 提供了具体的函数名、文件路径、行号
- [ ] 给出了可直接复制粘贴使用的修复代码
- [ ] 解释了每个修改的具体原因
- [ ] 涵盖了内存、性能、网络、存储、错误等多个维度
- [ ] 利用了correlations.jsonl识别问题间的关联关系

如果某个监控文件不存在，必须明确说明并解释影响。
如果没有源代码可查看，明确说明原因并建议如何获取源码。
绝不允许提供空泛的"应该优化"、"需要改进"这类无用建议。
"""

# Focus-specific prompts
FOCUS_PROMPTS = {
    "general": DEFAULT_ANALYSIS_PROMPT,
    
    "memory_leak": """
        专注于内存泄漏的源代码级深度分析。你必须找到具体的泄漏代码并提供精确修复。

        ## 强制执行步骤

        ### STEP 1: 内存泄漏函数定位 (必须执行)
        1. 分析heap_sampling.jsonl，提取TOP 10内存分配最高的**具体函数名**
        2. 分析memory.jsonl，计算每个时间段的内存增长率，找出增长最快的时段
        3. 统计事件监听器数量变化趋势，识别泄漏的具体组件

        ### STEP 2: 源码审查 (必须查看代码)
        对于每个高内存消耗函数：
        1. 在source_maps/metadata.jsonl中找到对应的源文件
        2. 使用Read工具打开具体的源文件
        3. 展示该函数的完整代码（至少30行上下文）
        4. 检查以下内存泄漏模式：
           - addEventListener后是否有removeEventListener
           - setInterval/setTimeout是否有clear操作
           - 闭包是否引用了大对象
           - React组件useEffect是否有返回清理函数
           - DOM引用是否及时置null

        ### STEP 3: 内存泄漏证据收集
        1. 对比组件挂载前后的内存差异
        2. 分析内存增长与用户操作的关联性
        3. 识别未清理资源的具体数量和类型

        ### STEP 4: 精确修复代码
        对于每个内存泄漏问题，提供：
        1. 泄漏代码的完整展示（标注具体哪几行有问题）
        2. 修复后的完整代码（包含所有清理逻辑）
        3. 内存泄漏的技术原理解释
        4. 修复效果的预估（预计减少多少MB内存）

        必须使用以下格式：
        ## 内存泄漏问题N: [具体问题]
        **泄漏函数**: [函数名]
        **文件位置**: [路径:行号]
        **泄漏类型**: [事件监听器/定时器/闭包引用/DOM引用]
        **预估泄漏量**: [每次操作泄漏XMB]

        ### 泄漏代码:
        ```javascript
        [完整的有问题代码，标注问题行]
        ```

        ### 修复代码:
        ```javascript
        [完整的修复代码，包含所有清理逻辑]
        ```
    """,
    
    "performance": """
        专注于主线程阻塞和性能瓶颈的源代码级分析。你必须找到具体的卡顿代码。

        ## 强制执行步骤

        ### STEP 1: 性能瓶颈精确定位 (必须执行)
        1. 分析longtask.jsonl，找到TOP 10耗时最长的具体任务
        2. 提取每个长任务的调用栈信息，定位到具体函数
        3. 分析gc.jsonl，计算GC阻塞主线程的总时间
        4. 识别导致主线程阻塞超过100ms的具体代码位置

        ### STEP 2: 源码性能审查 (必须查看代码)
        对于每个性能瓶颈：
        1. 根据调用栈信息，在sources/目录找到对应源文件
        2. 展示造成阻塞的完整函数代码（至少30行）
        3. 分析以下性能问题：
           - 同步循环处理大量数据
           - 频繁的DOM操作
           - 复杂的递归计算
           - 大量同步网络请求
           - 未优化的React渲染

        ### STEP 3: 性能影响量化
        1. 计算每个瓶颈函数的平均执行时间
        2. 统计函数调用频率（每秒调用多少次）
        3. 评估对用户体验的影响（阻塞时长）

        ### STEP 4: 性能优化代码
        对于每个性能问题，提供：
        1. 低效代码的完整展示（标注瓶颈行）
        2. 优化后的完整代码（异步化、分片处理）
        3. 性能提升预估（优化后耗时预期）
        4. 兼容性说明

        必须使用以下格式：
        ## 性能问题N: [具体问题]
        **瓶颈函数**: [函数名]
        **文件位置**: [路径:行号]
        **当前耗时**: [平均Xms，最长Xms]
        **调用频率**: [每秒X次]
        **阻塞影响**: [导致页面卡顿Xs]

        ### 低效代码:
        ```javascript
        [完整的低效代码，标注瓶颈行]
        ```

        ### 优化代码:
        ```javascript
        [完整的优化代码，使用异步、分片等技术]
        ```

        ### 优化效果:
        预期耗时减少: X% (从Xms降到Xms)
    """,
    
    "network": """
        专注于网络请求和API调用的源代码级分析。你必须找到具体的网络性能问题代码。

        ## 强制执行步骤

        ### STEP 1: 网络问题精确定位 (必须执行)
        1. 分析network.jsonl，找到TOP 10最慢的请求（按响应时间）
        2. 统计失败请求，按错误类型分组（timeout/404/500/限流等）
        3. 识别重复请求的具体URL和发起频率
        4. 找到大文件传输（>1MB）和耗时超过5秒的请求

        ### STEP 2: 请求源码审查 (必须查看代码)
        对于每个网络问题：
        1. 根据调用栈，在sources/目录找到发起请求的具体代码
        2. 展示网络请求的完整代码实现（至少25行）
        3. 分析以下网络问题：
           - 缺少请求超时设置
           - 未实现重试机制
           - 没有错误处理
           - 重复发起相同请求
           - 缺少请求缓存
           - 大量并发请求

        ### STEP 3: 网络性能量化
        1. 计算每个API的平均响应时间和成功率
        2. 统计请求频率和数据传输量
        3. 分析网络错误对用户体验的影响

        ### STEP 4: 网络优化代码
        对于每个网络问题，提供：
        1. 有问题的网络请求代码（标注问题点）
        2. 优化后的完整代码（添加缓存、重试、限流）
        3. 网络性能提升预估
        4. 兼容性和容错处理

        必须使用以下格式：
        ## 网络问题N: [具体问题]
        **请求URL**: [具体API地址]
        **发起函数**: [函数名]
        **文件位置**: [路径:行号]
        **当前性能**: [平均响应时间Xms，成功率X%]
        **请求频率**: [每分钟X次]

        ### 问题代码:
        ```javascript
        [完整的网络请求代码，标注问题行]
        ```

        ### 优化代码:
        ```javascript
        [优化后代码，包含缓存、重试、错误处理]
        ```

        ### 优化效果:
        预期响应时间减少: X% (从Xms降到Xms)
        预期成功率提升至: X%
    """,
    
    "errors": """
        专注于JavaScript错误和异常的源代码级根因分析。你必须定位到具体出错的代码行。

        ## 强制执行步骤

        ### STEP 1: 错误精确定位 (必须执行)
        1. 分析console.jsonl，找到TOP 10频率最高的错误消息
        2. 提取每个错误的完整堆栈跟踪信息
        3. 根据堆栈信息，定位到具体的文件名和行号
        4. 统计每个错误的发生频率和影响范围

        ### STEP 2: 源码错误审查 (必须查看代码)
        对于每个高频错误：
        1. 使用source_maps/metadata.jsonl解析源文件映射
        2. 在sources/目录找到出错的具体源文件
        3. 展示出错函数的完整代码（至少30行上下文）
        4. 分析以下错误模式：
           - 未捕获的Promise异常
           - null/undefined访问错误
           - 类型错误（TypeError）
           - 网络请求异常未处理
           - React组件生命周期错误
           - 第三方库调用错误

        ### STEP 3: 错误影响分析
        1. 统计每个错误对用户功能的影响
        2. 分析错误是否导致页面崩溃或功能失效
        3. 识别错误的触发条件和用户操作路径

        ### STEP 4: 错误修复代码
        对于每个错误，提供：
        1. 出错代码的完整展示（标注具体错误行）
        2. 修复后的完整代码（包含所有错误处理）
        3. 错误预防机制（参数检查、边界条件）
        4. 错误恢复策略（降级方案、用户提示）

        必须使用以下格式：
        ## 错误问题N: [具体错误类型]
        **错误信息**: [完整的错误消息]
        **出错函数**: [函数名]
        **文件位置**: [路径:行号]
        **错误频率**: [每小时X次]
        **触发条件**: [具体的触发场景]

        ### 错误代码:
        ```javascript
        [完整的出错代码，标注错误行和原因]
        ```

        ### 修复代码:
        ```javascript
        [完整的修复代码，包含错误处理和边界检查]
        ```

        ### 错误预防:
        [详细说明如何从代码设计上避免此类错误]

        ### 降级方案:
        [说明当错误发生时的用户体验保障措施]
    """
}


class PerformanceAnalyzer:
    """AI-powered performance analyzer using Claude Code SDK."""
    
    def __init__(self, session_dir: Path):
        """Initialize the analyzer with a session directory.
        
        Args:
            session_dir: Path to the session directory containing monitoring data
            
        Raises:
            FileNotFoundError: If the session directory doesn't exist
        """
        if not session_dir.exists():
            raise FileNotFoundError(f"Session directory not found: {session_dir}")
            
        self.session_dir = session_dir
        self.api_key_available = self.check_api_key()
        self.node_available, self.node_version = self.check_nodejs()
        
    def check_api_key(self) -> bool:
        """Check if ANTHROPIC_API_KEY is configured."""
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("⚠️  AI分析功能需要配置 ANTHROPIC_API_KEY")
            print("   1. 访问 https://console.anthropic.com 注册账号")
            print("   2. 获取API Key")
            print("   3. 设置环境变量：export ANTHROPIC_API_KEY='your-key-here'")
            print("\n   您仍可以使用 --analyze-sites 进行基础数据分析")
            return False
        return True
    
    def check_nodejs(self) -> Tuple[bool, str]:
        """Check Node.js availability and version.
        
        Returns:
            (available, version) tuple
        """
        try:
            result = subprocess.run(
                ['node', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.strip()  # Format: v18.12.0
                # Extract major version
                try:
                    major_version = int(version.split('.')[0][1:])  # Remove 'v' and get number
                    if major_version >= 18:
                        return True, version
                    else:
                        print(f"⚠️  Node.js版本过低: {version}")
                        print("   需要Node.js 18或更高版本")
                        print("   请升级Node.js: https://nodejs.org/")
                        return False, version
                except (ValueError, IndexError):
                    logger.warning(f"Failed to parse Node.js version: {version}")
                    return False, version
        except subprocess.TimeoutExpired:
            print("⚠️  Node.js版本检测超时")
            return False, ""
        except FileNotFoundError:
            print("⚠️  未检测到Node.js环境")
            print("   Claude Code SDK需要Node.js 18+")
            print("   请安装Node.js: https://nodejs.org/")
            return False, ""
        except Exception as e:
            logger.warning(f"Node.js check failed: {e}")
            return False, ""
        
        return False, ""
    
    def build_prompt(self, focus: str = "general") -> tuple[str, str]:
        """Build system prompt and analysis prompt based on focus.
        
        Args:
            focus: Analysis focus type
            
        Returns:
            (system_prompt, analysis_prompt) tuple
        """
        system_prompt = DEFAULT_SYSTEM_PROMPT
        analysis_prompt = FOCUS_PROMPTS.get(focus, DEFAULT_ANALYSIS_PROMPT)
        return system_prompt, analysis_prompt
    
    async def analyze(self,
                     focus: str = "general", 
                     custom_prompt: str = None) -> bool:
        """Execute AI analysis.
        
        Args:
            focus: Analysis focus (general, memory_leak, performance, network, errors)
            custom_prompt: Custom analysis prompt (overrides focus)
            
        Returns:
            True if analysis completed successfully, False otherwise
        """
        # Check if Claude SDK is available
        if not CLAUDE_SDK_AVAILABLE:
            print("\n无法使用AI分析，Claude SDK未正确安装")
            print("请确保已安装：pip install claude-code-sdk")
            print("提示：可以使用 --analyze-sites 进行基础数据分析")
            return False
        
        # Check prerequisites
        if not self.api_key_available:
            print("\n无法使用AI分析，缺少API Key")
            print("提示：可以使用 --analyze-sites 进行基础数据分析")
            return False
            
        if not self.node_available:
            print("\n无法使用AI分析，Node.js环境不满足要求")
            print("提示：可以使用 --analyze-sites 进行基础数据分析")
            return False
        
        # Build prompts
        if custom_prompt:
            # Custom mode
            system_prompt = DEFAULT_SYSTEM_PROMPT
            analysis_prompt = custom_prompt
        else:
            # Preset mode
            system_prompt, analysis_prompt = self.build_prompt(focus)
        
        # Add data directory context
        full_prompt = f"""
        监控数据目录：{self.session_dir}
        
        {analysis_prompt}
        """
        
        # Configure Claude Code SDK options
        options = ClaudeCodeOptions(
            system_prompt=system_prompt,
            cwd=str(self.session_dir),
            allowed_tools=["Read", "Write", "Bash", "Grep"]
        )
        
        print("🔧 准备AI分析环境...")
        print(f"   • 数据目录: {self.session_dir}")
        print(f"   • 分析焦点: {focus}")
        print(f"   • Node.js: {self.node_version}")
        print("   • 可用工具: Read, Write, Bash, Grep")
        
        try:
            print(f"\n开始AI分析 (焦点: {focus})...")
            print("=" * 50)
            print("🤖 Claude 正在分析数据，请稍候...\n")
            
            # Prepare to collect analysis results
            analysis_results = []
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            message_count = 0
            start_time = time.time()
            last_output_time = start_time
            
            # Execute query and stream results with improved output handling
            async for message in query(prompt=full_prompt, options=options):
                message_count += 1
                
                # Try different message attributes that Claude SDK might use
                content = None
                if hasattr(message, 'result'):
                    content = message.result
                elif hasattr(message, 'text'):
                    content = message.text
                elif hasattr(message, 'content'):
                    content = message.content
                elif hasattr(message, 'data'):
                    content = message.data
                else:
                    # Debug: print message structure for the first few messages
                    if message_count <= 3:
                        print(f"🔍 调试信息 - 消息结构: {type(message)} - 属性: {[attr for attr in dir(message) if not attr.startswith('_')]}")
                    content = str(message)  # Fallback to string representation
                
                # Handle different content types
                if content:
                    display_content = None
                    
                    if isinstance(content, dict):
                        # Handle dictionary content - extract text from common fields
                        if 'text' in content:
                            display_content = content['text']
                        elif 'content' in content:
                            display_content = content['content']
                        elif 'message' in content:
                            display_content = content['message']
                        elif 'result' in content:
                            display_content = content['result']
                        else:
                            # If no common text field, convert to string representation
                            display_content = str(content)
                    elif isinstance(content, str):
                        display_content = content
                    else:
                        # Convert other types to string
                        display_content = str(content)
                    
                    # Check if we have meaningful content to display
                    if display_content and display_content.strip():
                        # Ensure immediate output by flushing stdout
                        print(display_content, end='', flush=True)
                        analysis_results.append(display_content)
                        last_output_time = time.time()
                    else:
                        # Show progress indicator for empty/whitespace-only content
                        current_time = time.time()
                        if current_time - last_output_time > 10:  # No output for 10 seconds
                            elapsed = int(current_time - start_time)
                            print(f"\n[{elapsed}s] 🔄 分析进行中...", end='', flush=True)
                            last_output_time = current_time
                        else:
                            print(".", end='', flush=True)
                else:
                    # Show progress indicator for None/empty messages
                    current_time = time.time()
                    if current_time - last_output_time > 10:  # No output for 10 seconds
                        elapsed = int(current_time - start_time)
                        print(f"\n[{elapsed}s] 🔄 分析进行中...", end='', flush=True)
                        last_output_time = current_time
                    else:
                        print(".", end='', flush=True)
                
                # Allow other tasks to run
                await asyncio.sleep(0)
            
            # Final statistics
            total_time = int(time.time() - start_time)
            print("\n" + "=" * 50)
            print(f"✅ 分析完成 - 耗时: {total_time}s - 消息数: {message_count}")
            
            # Save analysis report to file
            if analysis_results:
                report_filename = f"ai_analysis_{focus}_{timestamp}.md"
                report_path = self.session_dir / report_filename
                
                # Create markdown report
                report_content = f"""# BrowserFairy AI Analysis Report

**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**分析焦点**: {focus}  
**数据目录**: {self.session_dir}  
**分析耗时**: {total_time}秒  
**处理消息**: {message_count}条

---

## 分析结果

{"".join(analysis_results)}

---

*此报告由BrowserFairy AI分析功能自动生成*
"""
                
                # Write report to file
                report_path.write_text(report_content, encoding='utf-8')
                print(f"📄 AI分析报告已保存: {report_path}")
            else:
                print("⚠️  AI分析完成但无输出结果")
                print("   这可能是因为:")
                print("   1. 数据目录为空或无有效监控数据")
                print("   2. API调用出现问题")  
                print("   3. 提示词需要调整")
            
            return True
            
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            print(f"\nAI分析失败: {e}")
            return False
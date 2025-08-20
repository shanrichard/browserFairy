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
- memory.jsonl: 内存使用时序数据，每行一条记录
- heap_sampling.jsonl: 内存分配采样，包含函数级统计
- console.jsonl: 控制台日志，包含错误和警告
- network.jsonl: 网络请求生命周期数据
- gc.jsonl: 垃圾回收事件
- longtask.jsonl: 长任务（>50ms）记录
- source_maps/: Source Map文件和元数据（2-6已实现）
- sources/: 提取的源代码文件（2-6已实现）
"""

DEFAULT_ANALYSIS_PROMPT = """
请编写Python代码来分析监控数据，不要直接读取全部文件内容。

分析策略：
1. 先了解数据规模和结构
   - 检查文件大小和数量
   - 采样查看数据格式（只读几行示例）
   - 检查source_maps/和sources/目录，了解有哪些源代码可用

2. 编写高效的统计分析代码
   - 使用流式处理遍历大文件
   - 提取关键指标和统计信息
   - 识别异常模式和问题

3. 对发现的问题进行深入分析
   - 定点读取相关的详细记录
   - 利用source_maps/metadata.jsonl找到对应的源文件
   - 在sources/目录中查看具体的源代码实现
   - 结合错误堆栈和源码定位问题根源

4. 生成分析报告
   - 总结主要发现
   - 提供具体案例（包含源码片段）
   - 给出精确的优化建议

请根据实际数据情况，灵活选择合适的分析方法和工具。
记住：用代码分析，不要试图一次性读取整个文件到内存。
"""

# Focus-specific prompts
FOCUS_PROMPTS = {
    "general": DEFAULT_ANALYSIS_PROMPT,
    
    "memory_leak": """
        专注于内存泄漏分析，结合源代码深度诊断：
        
        1. 分析heap_sampling.jsonl中的内存分配数据
           - 统计哪些函数分配了最多内存
           - 识别持续增长的分配模式
           - 注意使用流式处理，不要一次性加载整个文件
           
        2. 源代码级内存泄漏定位
           - 根据heap_sampling中的函数名，在sources/目录查找对应源代码
           - 分析高内存占用函数的具体实现
           - 识别潜在的内存泄漏模式：
             * 未清理的事件监听器
             * 闭包引用的大对象
             * 循环引用
             * 未销毁的定时器
           
        3. 内存增长趋势与代码关联
           - 分析memory.jsonl中的JS Heap增长率
           - 关联DOM节点数增长与具体的组件代码
           - 检查事件监听器泄漏的代码位置
           
        4. 提供源码级优化建议
           - 基于具体代码给出内存优化方案
           - 指出需要添加的清理逻辑
           - 推荐内存管理最佳实践
    """,
    
    "performance": """
        专注于性能瓶颈分析：
        
        1. 分析longtask.jsonl中的长任务数据
           - 统计长任务的数量、持续时间分布
           - 识别最耗时的操作类型
           - 找出频繁出现的长任务模式
           
        2. 分析gc.jsonl中的垃圾回收情况
           - 计算GC频率和总耗时
           - 识别内存压力大的时段
           - 分析GC与性能问题的关联
           
        3. 综合性能指标分析
           - 检查脚本执行时间
           - 分析布局和样式重计算
           - 识别主线程阻塞情况
           
        4. 提供性能优化建议
           - 基于发现的瓶颈提出改进方案
           - 推荐代码分割、异步处理等策略
    """,
    
    "network": """
        专注于网络性能分析：
        
        1. 分析network.jsonl中的请求数据
           - 统计请求成功率、失败原因
           - 计算响应时间分布（P50/P95/P99）
           - 识别慢接口和超时请求
           
        2. 资源加载性能分析
           - 找出大文件传输（如>500KB的资源）
           - 检测重复请求和无效请求
           - 分析请求并发情况
           
        3. API性能深入分析
           - 对慢接口进行详细分析
           - 检查错误率变化趋势
           - 分析网络瀑布图模式
           
        4. 提供网络优化建议
           - 基于分析结果推荐CDN、缓存策略
           - 建议请求合并或分片方案
    """,
    
    "errors": """
        专注于错误和异常分析，充分利用源代码：
        
        1. 分析console.jsonl中的错误日志
           - 统计错误类型、级别和频率
           - 识别高频错误消息
           - 提取错误堆栈中的文件位置和行号
           
        2. 源代码级别的错误定位
           - 读取source_maps/metadata.jsonl找到scriptId映射
           - 在sources/目录中查看出错代码的具体实现
           - 分析错误发生的代码上下文
           - 识别代码模式问题（如未处理的Promise、空值检查等）
           
        3. 错误根因分析
           - 结合堆栈信息和源码，精确定位问题
           - 分析错误传播路径
           - 检查相关联的组件和模块
           
        4. 提供精准的修复建议
           - 基于源码给出具体的代码修改建议
           - 指出需要添加的错误处理
           - 推荐防御性编程实践
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
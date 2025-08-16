#!/bin/bash

# BrowserFairy 安装脚本
# 支持多种安装方式，自动检测环境

set -e

echo "🧚 BrowserFairy 安装脚本"
echo "=========================="

# 检查Python版本
check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON=python3
    elif command -v python &> /dev/null; then
        PYTHON=python
    else
        echo "❌ 错误：未找到Python。请先安装Python 3.11+"
        exit 1
    fi

    # 检查Python版本
    PYTHON_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]); then
        echo "❌ 错误：Python版本过低 ($PYTHON_VERSION)，需要3.11+"
        exit 1
    fi
    
    echo "✓ Python版本: $PYTHON_VERSION"
}

# 检查pip
check_pip() {
    if command -v pip3 &> /dev/null; then
        PIP=pip3
    elif command -v pip &> /dev/null; then
        PIP=pip
    else
        echo "❌ 错误：未找到pip。请先安装pip"
        exit 1
    fi
    echo "✓ 找到pip: $PIP"
}

# 方式1: 从wheel文件安装（推荐）
install_from_wheel() {
    if [ -f "dist/browserfairy-0.1.0-py3-none-any.whl" ]; then
        echo "📦 从wheel文件安装..."
        $PIP install --force-reinstall dist/browserfairy-0.1.0-py3-none-any.whl
        return 0
    else
        echo "⚠️  wheel文件不存在，尝试其他安装方式..."
        return 1
    fi
}

# 方式2: 从源码安装（开发模式）
install_from_source() {
    if [ -f "pyproject.toml" ]; then
        echo "🔧 从源码安装（开发模式）..."
        $PIP install -e .
        return 0
    else
        echo "⚠️  pyproject.toml不存在，尝试其他安装方式..."
        return 1
    fi
}

# 方式3: 使用uv安装（如果可用）
install_with_uv() {
    if command -v uv &> /dev/null; then
        echo "⚡ 使用uv安装..."
        uv sync
        echo "✓ 依赖安装完成，使用 'uv run browserfairy --help' 运行"
        return 0
    else
        return 1
    fi
}

# 验证安装
verify_installation() {
    echo "🧪 验证安装..."
    
    if command -v browserfairy &> /dev/null; then
        echo "✅ 安装成功！"
        echo ""
        echo "📋 快速使用指南："
        echo "1. 启动Chrome调试模式："
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "   open -a 'Google Chrome' --args --remote-debugging-port=9222"
        else
            echo "   google-chrome --remote-debugging-port=9222"
        fi
        echo ""
        echo "2. 测试连接："
        echo "   browserfairy --test-connection"
        echo ""
        echo "3. 开始监控（前台）："
        echo "   browserfairy --monitor-comprehensive"
        echo ""
        echo "4. 后台监控（推荐）："
        echo "   browserfairy --monitor-comprehensive --daemon"
        echo ""
        echo "📖 完整中文文档：README.md"
        echo "💡 使用技巧：Chrome关闭后daemon会自动退出，无需手动清理"
        return 0
    else
        echo "❌ 安装验证失败。请检查PATH环境变量或尝试重新安装。"
        return 1
    fi
}

# 主安装流程
main() {
    echo "🔍 检查系统环境..."
    check_python
    check_pip
    
    echo ""
    echo "🚀 开始安装..."
    
    # 尝试各种安装方式
    if install_from_wheel; then
        echo "✓ wheel安装成功"
    elif install_with_uv; then
        echo "✓ uv安装成功"
        exit 0  # uv方式不需要验证browserfairy命令
    elif install_from_source; then
        echo "✓ 源码安装成功"
    else
        echo "❌ 所有安装方式都失败了"
        echo ""
        echo "🔧 手动安装步骤："
        echo "1. 确保Python 3.11+"
        echo "2. 运行: pip install dist/browserfairy-0.1.0-py3-none-any.whl"
        echo "3. 或者: pip install -e ."
        exit 1
    fi
    
    echo ""
    verify_installation
}

# 显示帮助
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -h, --help     显示帮助信息"
    echo "  --uv           强制使用uv安装"
    echo "  --wheel        强制使用wheel文件安装"
    echo "  --source       强制从源码安装"
    echo ""
    echo "示例:"
    echo "  $0              # 自动选择最佳安装方式"
    echo "  $0 --wheel      # 强制使用wheel文件"
    echo "  $0 --uv         # 强制使用uv"
}

# 处理命令行参数
case "${1:-}" in
    -h|--help)
        show_help
        exit 0
        ;;
    --uv)
        check_python
        install_with_uv || (echo "❌ uv安装失败"; exit 1)
        ;;
    --wheel)
        check_python
        check_pip
        install_from_wheel || (echo "❌ wheel安装失败"; exit 1)
        verify_installation
        ;;
    --source)
        check_python
        check_pip
        install_from_source || (echo "❌ 源码安装失败"; exit 1)
        verify_installation
        ;;
    "")
        main
        ;;
    *)
        echo "❌ 未知参数: $1"
        show_help
        exit 1
        ;;
esac
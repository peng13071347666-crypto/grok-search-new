#!/bin/bash
# grok-search 一键安装脚本
# 用法: ./install.sh
# 环境变量: GROK_API_URL, GROK_API_KEY 可预设; 否则会交互询问

set -euo pipefail

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}ℹ${NC}  $1"; }
success() { echo -e "${GREEN}✓${NC}  $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
error() { echo -e "${RED}✗${NC}  $1"; exit 1; }

# 1. 检查 Python
info "检查 Python..."
if ! command -v python3 &> /dev/null; then
    error "找不到 python3。请先安装 Python 3.10+"
fi
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [ "$(echo "$PY_VERSION < 3.10" | bc -l 2>/dev/null || python3 -c "print(1 if $PY_VERSION < 3.10 else 0)")" = "1" ]; then
    error "Python $PY_VERSION 太旧，需要 3.10+"
fi
success "Python $PY_VERSION"

# 2. 创建虚拟环境
info "创建虚拟环境..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
success "虚拟环境就绪"

# 3. 安装依赖
info "安装依赖..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .
success "依赖已安装"

# 4. 链接到 PATH
info "链接到 ~/.local/bin..."
mkdir -p ~/.local/bin
ln -sf "$(pwd)/bin/grok-search" ~/.local/bin/grok-search
success "已链接: ~/.local/bin/grok-search"

# 检查 PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "~/.local/bin 不在 PATH 中"
    echo "    请执行: export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "    或添加到 ~/.zshrc / ~/.bashrc"
fi

# 5. 配置 Grok API
info "配置 Grok API..."
mkdir -p ~/.config/smart-search

if [ -f ~/.config/smart-search/config.json ]; then
    warn "检测到现有配置 ~/.config/smart-search/config.json"
    read -p "    是否覆盖? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        success "保留现有配置"
    else
        CONFIGURE=1
    fi
else
    CONFIGURE=1
fi

if [ "${CONFIGURE:-0}" = "1" ]; then
    # 用环境变量 or 交互询问
    if [ -n "${GROK_API_URL:-}" ] && [ -n "${GROK_API_KEY:-}" ]; then
        API_URL="$GROK_API_URL"
        API_KEY="$GROK_API_KEY"
        API_MODEL="${GROK_API_MODEL:-grok-4.20-multi-agent-xhigh}"
    else
        echo ""
        echo "请提供 Grok API（任何 OpenAI-compatible 端点）:"
        read -p "  API URL [https://api.x.ai/v1]: " API_URL
        API_URL="${API_URL:-https://api.x.ai/v1}"
        read -p "  API Key: " API_KEY
        read -p "  模型名 [grok-4.20-multi-agent-xhigh]: " API_MODEL
        API_MODEL="${API_MODEL:-grok-4.20-multi-agent-xhigh}"
    fi

    cat > ~/.config/smart-search/config.json <<EOF
{
  "OPENAI_COMPATIBLE_API_URL": "$API_URL",
  "OPENAI_COMPATIBLE_API_KEY": "$API_KEY",
  "OPENAI_COMPATIBLE_MODEL": "$API_MODEL",
  "primary_api_mode": "chat-completions"
}
EOF
    chmod 600 ~/.config/smart-search/config.json
    success "已配置: ~/.config/smart-search/config.json"
fi

# 6. 配置补源 API（可选）
info "配置补源 API（可选）..."
mkdir -p ~/.config/grok-search

if [ ! -f ~/.config/grok-search/config.json ]; then
    cat > ~/.config/grok-search/config.json <<'EOF'
{
}
EOF
    chmod 600 ~/.config/grok-search/config.json
fi

echo ""
echo "如需补源 API（不配也能用），现在配置:"

# Brave
if [ -z "${GROK_SEARCH_BRAVE_API_KEY:-}" ]; then
    read -p "  Brave API Key (回车跳过): " BRAVE_KEY
    [ -n "$BRAVE_KEY" ] && grok-search config set BRAVE_API_KEY "$BRAVE_KEY" 2>/dev/null || warn "  跳过 Brave"
else
    grok-search config set BRAVE_API_KEY "$GROK_SEARCH_BRAVE_API_KEY" 2>/dev/null
    success "  Brave 已配置"
fi

# Serper
if [ -z "${GROK_SEARCH_SERPER_API_KEY:-}" ]; then
    read -p "  Serper API Key (回车跳过): " SERPER_KEY
    [ -n "$SERPER_KEY" ] && grok-search config set SERPER_API_KEY "$SERPER_KEY" 2>/dev/null || warn "  跳过 Serper"
else
    grok-search config set SERPER_API_KEY "$GROK_SEARCH_SERPER_API_KEY" 2>/dev/null
    success "  Serper 已配置"
fi

# Tavily
if [ -z "${GROK_SEARCH_TAVILY_API_KEY:-}" ]; then
    read -p "  Tavily API Key (回车跳过): " TAVILY_KEY
    [ -n "$TAVILY_KEY" ] && grok-search config set TAVILY_API_KEY "$TAVILY_KEY" 2>/dev/null || warn "  跳过 Tavily"
else
    grok-search config set TAVILY_API_KEY "$GROK_SEARCH_TAVILY_API_KEY" 2>/dev/null
    success "  Tavily 已配置"
fi

# 7. 验证
echo ""
info "验证安装..."
if command -v grok-search &> /dev/null; then
    success "grok-search 在 PATH 中"
else
    warn "grok-search 不在 PATH 中, 但可执行: $(pwd)/bin/grok-search"
fi

# 跑 doctor（不强制成功——可能 API 还没配好）
if grok-search doctor --format json &> /tmp/grok_doctor.json; then
    MODELS=$(python3 -c "import json; d=json.load(open('/tmp/grok_doctor.json')); print(len(d.get('available_models', [])))" 2>/dev/null || echo "?")
    success "doctor 通过, 可用模型数: $MODELS"
else
    warn "doctor 失败, 但已安装完成. 请检查 ~/.config/smart-search/config.json"
fi

# 8. 总结
echo ""
echo "=================================="
success "安装完成！"
echo "=================================="
echo ""
echo "下一步:"
echo "  1. 验证: grok-search doctor"
echo "  2. 试一下: grok-search search \"Hello\" --format json"
echo "  3. 抓取页面: grok-search fetch \"https://pi.dev/\""
echo "  4. 看完整文档: cat README.md"
echo "  5. 作为 pi skill 安装: ln -s \"\$(pwd)/SKILL.md\" ~/.pi/agent/skills/grok-search/SKILL.md"
echo ""

#!/bin/bash
# 简单的脚本，使用 pandoc 将 markdown 编译为 epub 电子书

if ! command -v pandoc &> /dev/null; then
    echo "错误：未找到 pandoc 命令。"
    echo "请先安装 pandoc："
    echo " macOS: brew install pandoc"
    echo " Ubuntu/Debian: sudo apt install pandoc"
    exit 1
fi

echo "正在将 Markdown 转换为 EPUB 电子书..."

# 按顺序合并文件
pandoc 01_stage1_basic.md \
       02_stage2_packet_filtering.md \
       03_stage3_advanced_structures.md \
       04_stage4_state_machine.md \
       05_stage5_nat.md \
       06_stage6_best_practices.md \
       07_review_plan.md \
       08_final_exam.md \
       -o nftables_tutorial.epub \
       --toc \
       --metadata title="像学 C 语言一样学 nftables" \
       --metadata creator="Sweetcs" \
       --metadata language="zh-CN"

if [ $? -eq 0 ]; then
    echo "成功！已生成电子书文件：nftables_tutorial.epub"
else
    echo "生成失败，请检查 pandoc 报错信息。"
fi

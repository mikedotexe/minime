#!/bin/bash
# create_archive.sh - Create clean archive of MikesSpatialMind codebase
# Excludes runtime files, backups, and test results
# Creates timestamped tar.gz with source code only

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_NAME="mikeconsciousness_${TIMESTAMP}.tar.gz"

echo "================================================"
echo "MikesSpatialMind Codebase Archiver"
echo "================================================"
echo ""
echo "Creating archive: ${ARCHIVE_NAME}"
echo ""

# Create exclusion list
cat > .archive_exclude << 'EOF'
# Python cache
__pycache__/
*.pyc
*.pyo
*.pyd
.Python

# Backup files
*_backup_*.py
*.bak
*.swp
*.swo
*~

# Test results
test_results_*.json
comparison_report_*.md
test_output.log

# OS files
.DS_Store
Thumbs.db

# IDE files
.vscode/
.idea/
*.sublime-*

# Temporary files
*.tmp
.cache/

# Archive exclusion file itself
.archive_exclude
EOF

echo "Exclusions configured:"
echo "  - Python cache and backups"
echo "  - Test results and reports"
echo "  - OS/IDE temporary files"
echo ""
echo "✅ Including runtime state files (*.pkl, logs, memories)"
echo ""
echo "Archiving source code..."
echo ""

# Create archive
tar -czf "${ARCHIVE_NAME}" \
    --exclude-from=.archive_exclude \
    *.py \
    *.sh \
    *.md \
    *.pkl \
    *.log \
    *.json \
    corpus/ \
    thoughts_queue/ \
    7-spirals-pi/ \
    2>/dev/null

# Clean up exclusion list
rm .archive_exclude

# Show results
if [ -f "${ARCHIVE_NAME}" ]; then
    SIZE=$(ls -lh "${ARCHIVE_NAME}" | awk '{print $5}')
    echo "✅ Archive created successfully!"
    echo ""
    echo "   File: ${ARCHIVE_NAME}"
    echo "   Size: ${SIZE}"
    echo ""
    echo "📦 Contents (first 30 files):"
    tar -tzf "${ARCHIVE_NAME}" | head -30
    TOTAL=$(tar -tzf "${ARCHIVE_NAME}" | wc -l)
    if [ "$TOTAL" -gt 30 ]; then
        echo "   ... (${TOTAL} files total)"
    fi
    echo ""
    echo "📝 To extract:"
    echo "   tar -xzf ${ARCHIVE_NAME}"
    echo ""
    echo "📤 To transfer:"
    echo "   scp ${ARCHIVE_NAME} user@server:~/backups/"
    echo ""
else
    echo "❌ Failed to create archive"
    exit 1
fi

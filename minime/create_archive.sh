#!/bin/bash
# Archive minime codebase for PE handoff
# Creates clean tarball with all band-stop infrastructure

set -e

ARCHIVE_NAME="minime_bandstop_$(date +%Y%m%d_%H%M%S).tar.gz"
TEMP_DIR="minime_archive_temp"

echo "📦 Creating archive: $ARCHIVE_NAME"

# Create temp directory
mkdir -p "$TEMP_DIR"

# Copy relevant files
echo "  → Copying source files..."
cp -r src "$TEMP_DIR/"
cp -r shaders "$TEMP_DIR/"
cp -r examples "$TEMP_DIR/"
cp Cargo.toml "$TEMP_DIR/"
cp Cargo.lock "$TEMP_DIR/" 2>/dev/null || true
cp INTEGRATION_STATUS.md "$TEMP_DIR/"
cp README.md "$TEMP_DIR/" 2>/dev/null || true

# Create archive
echo "  → Creating tarball..."
tar -czf "$ARCHIVE_NAME" -C "$TEMP_DIR" .

# Cleanup
rm -rf "$TEMP_DIR"

# Show summary
SIZE=$(du -h "$ARCHIVE_NAME" | cut -f1)
FILES=$(tar -tzf "$ARCHIVE_NAME" | wc -l | tr -d ' ')

echo ""
echo "✅ Archive created successfully!"
echo "   File: $ARCHIVE_NAME"
echo "   Size: $SIZE"
echo "   Files: $FILES"
echo ""
echo "📋 Contents:"
tar -tzf "$ARCHIVE_NAME" | head -20
echo "   ... (+ $(($FILES - 20)) more files)"
echo ""
echo "🚀 To extract:"
echo "   tar -xzf $ARCHIVE_NAME"
echo ""
echo "📖 Read INTEGRATION_STATUS.md for complete handoff notes"

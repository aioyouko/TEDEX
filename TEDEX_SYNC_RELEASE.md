# TEDEX v1.2.1 同步发布流程

目标仓库：

```text
https://github.com/aioyouko/TEDEX
```

本地准备发布的包：

```bash
RELEASE="/Users/chenheyang/Library/CloudStorage/OneDrive-NorthwesternUniversity/02-Northwestern Lab/te_agent_workspace/external/github/te-analysis-plotting-v1.2.1"
REMOTE="https://github.com/aioyouko/TEDEX.git"
WORK="/tmp/TEDEX-sync"
TAG="v1.2.1"
```

如果你用 SSH，可以改成：

```bash
REMOTE="git@github.com:aioyouko/TEDEX.git"
```

## 1. 发布前检查

确认版本号已经对齐：

```bash
cd "$RELEASE"
cat VERSION
grep '^version =' pyproject.toml
```

确认除了 `data/demo/`，其他数据目录只含 `.gitkeep` 或为空：

```bash
find data -path data/demo -prune -o -type f -print | sort
```

确认没有 `.env`、缓存或 macOS 元数据：

```bash
find . -name .DS_Store -o -name __pycache__ -o -name '*.pyc' -o -name .env
```

如果有 `.DS_Store`，发布时的 `rsync` 命令会排除它们；也可以手动删除后再继续。

## 2. Clone 远端仓库

```bash
rm -rf "$WORK"
git clone "$REMOTE" "$WORK"
cd "$WORK"
git status --short
```

确认远端还没有这个 tag：

```bash
git ls-remote --tags origin "$TAG"
```

没有输出才继续。如果已经有输出，先去 GitHub 确认是不是已经发布过。

## 3. 预览同步变更

先 dry-run，看会新增、修改、删除什么：

```bash
rsync -an --delete \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$RELEASE"/ "$WORK"/
```

如果远端仓库有想保留但 release 包里没有的 GitHub-only 文件，例如
`.github/` 或 `LICENSE`，请把它们复制进 `$RELEASE`，或者在正式同步时额外
加 `--exclude '.github/'`、`--exclude 'LICENSE'`。

## 4. 正式同步并检查

```bash
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$RELEASE"/ "$WORK"/

cd "$WORK"
git status --short
git diff --stat
```

再做一次隐私检查：

```bash
find data -path data/demo -prune -o -type f -print | sort
find . -name .DS_Store -o -name __pycache__ -o -name '*.pyc' -o -name .env
```

## 5. 提交、打 tag、推送

```bash
git add -A
git commit -m "Release v1.2.1"
git tag -a "$TAG" -m "Release v1.2.1"
git push origin main
git push origin "$TAG"
```

如果 `git commit` 提示 `nothing to commit`，不要直接打新 tag；先确认远端是否
已经和本地 release 包一致。

## 6. 创建 GitHub Release

网页方式：

1. 打开 `https://github.com/aioyouko/TEDEX/releases/new`。
2. 选择 tag `v1.2.1`。
3. 标题写 `TEDEX v1.2.1`。
4. Release notes 可以用下面这段。
5. 点击 `Publish release`。

Release notes:

```text
- Added bar and grouped-bar plotting support in flexible_plot.py.
- Added reusable bar chart recipes under configs/plot_recipes/bar/.
- Added thermoelectric property recipes under configs/plot_recipes/thermoeletric/.
- Added public demo inputs and gallery figures under data/demo/.
- Refreshed the GitHub README for the v1.2.1 examples.
```

如果安装了 GitHub CLI，也可以：

```bash
cat > /tmp/TEDEX-v1.2.1-notes.md <<'EOF'
- Added bar and grouped-bar plotting support in flexible_plot.py.
- Added reusable bar chart recipes under configs/plot_recipes/bar/.
- Added thermoelectric property recipes under configs/plot_recipes/thermoeletric/.
- Added public demo inputs and gallery figures under data/demo/.
- Refreshed the GitHub README for the v1.2.1 examples.
EOF

gh release create v1.2.1 \
  --repo aioyouko/TEDEX \
  --title "TEDEX v1.2.1" \
  --notes-file /tmp/TEDEX-v1.2.1-notes.md
```

## 快速版命令

确认 `$RELEASE` 正确后，可以按这一组命令走：

```bash
RELEASE="/Users/chenheyang/Library/CloudStorage/OneDrive-NorthwesternUniversity/02-Northwestern Lab/te_agent_workspace/external/github/te-analysis-plotting-v1.2.1"
REMOTE="https://github.com/aioyouko/TEDEX.git"
WORK="/tmp/TEDEX-sync"
TAG="v1.2.1"

rm -rf "$WORK"
git clone "$REMOTE" "$WORK"

git -C "$WORK" ls-remote --tags origin "$TAG"

rsync -an --delete \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$RELEASE"/ "$WORK"/

rsync -a --delete \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$RELEASE"/ "$WORK"/

cd "$WORK"
find data -path data/demo -prune -o -type f -print | sort
find . -name .DS_Store -o -name __pycache__ -o -name '*.pyc' -o -name .env

git status --short
git diff --stat
git add -A
git commit -m "Release v1.2.1"
git tag -a "$TAG" -m "Release v1.2.1"
git push origin main
git push origin "$TAG"
```

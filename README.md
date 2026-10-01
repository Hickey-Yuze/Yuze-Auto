<img src="src/assets/images/icon-128.png" width="64"/>

# Yuze Auto

一个通过**连接块**来自动化浏览器操作的扩展。自动填表、重复任务、截图、抓取数据，还能按计划定时执行。

## 特性

- 🧩 **块工作流**：拖拽连接积木块，零代码搭建自动化流程
- 🇨🇳 **全量中文界面**：编辑器、设置、弹窗均已汉化
- 🐍 **JS / Python 代码块**：内置 `yuze` SDK（补全、悬停示例、API 速查）
- 📝 **注释引用虚线**：注释块与工作流块可视化关联，不干扰执行
- ♻️ **回收站**：删除的工作流可还原（保留 30 天）
- 🖼️ **弹窗壁纸**：自定义弹窗背景，支持裁剪调整与实时预览

## 下载安装（无需打包）

到 [Releases](https://github.com/Hickey-Yuze/Yuze-Auto/releases) 下载最新的 `Yuze-Auto-v*.zip`，解压后：

1. 打开 `chrome://extensions`，右上角开启「开发者模式」
2. 点「加载已解压的扩展程序」，选择解压出的文件夹

## 本地构建（二次开发）

```bash
npm install --legacy-peer-deps
npm run build
```

构建完成后，在浏览器 `chrome://extensions` 开启「开发者模式」→「加载已解压的扩展程序」→ 选择 `build` 目录。

## 许可

本项目基于 [MIT](LICENSE.txt) 协议开源。

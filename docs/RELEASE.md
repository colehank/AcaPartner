# 开发预览与发布

当前只提供统一科研工作台。旧版工作桌、独立文稿试用页和早期原型已从源码与构建入口移除；项目数据库、稿件、草稿与历史修订不受影响。

## 生成安装包

先按 README 安装前端依赖并构建，再运行 `python3 tools/build.py --output dist`。工具使用公开文件正向清单收集 Python 模块、当前前端源码/公共许可、预构建、当前文档和自包含测试，生成带 SHA-256 的 manifest。仅在本机生成，不自动发布或上传。

安装器入口：`python3 tools/install.py dist/research-partner.tar.gz --target /空目录`；安装后运行 `python3 tools/start_local.py`。默认工作桌模式不启动任务执行器或消费旧队列。源码升级和旧界面删除均不代替私有资料备份或格式迁移。

## 范围

使用与实现入口见 [当前指南](workbench-guide.md)、[产品文档](product/README.md)与[文稿接入](architecture/document-adapters.md)。原始研究数据、账号和凭据、本机运行台账、私有输入、临时验收输出不进入安装包。

正式分发前仍须核对实际包含依赖的许可证和支持范围；主项目 MIT 不重新授权 SuperDoc 的 AGPL 部分或必需的专有 DOCX 引擎。当前为本机开发集成，生成安装包不等于获得闭源再分发或生产许可。

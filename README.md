# 智能游戏NPC客服 (Game_NPC_Agent)

**描述**  
这是一个游戏NPC对话优化的AI Agent示例项目，是一个扫地机器人选购项目的复现项目。它旨在丰富NPC的对话内容，让对话显得更拟人化，同时不会对主线剧情或游戏活动产生较大影响。  
目前仅支持中文。

## 安装步骤
1. 克隆仓库：
   ```bash
   git clone https://github.com/lightporta/Agent_1.git

2. 安装依赖：
   ```bash
   pip install openai
   pip install langchain langchain_community langchain-ollama dashscope_chromadb

3. 使用示例
   在windows外部终端进入app.py所在上级目录输入：
   ```bash
   streamlit run app.py

4. 项目结构与文件组织
 
                   /agent       存放中间件与agent本身定义与工具定义
                   /config      使用配置文件
                   /data        外部信息
                   /logs        文件日志
                   /model       大模型工厂（包含大语言模型，聊天模型，嵌入模型）
                   /prompts     提示词工程
                   /rag         存放服务类与向量库
                   /utils       基础工具（包括路径，提示词加载，配置文件处理，文件处理工具）
                   app.py       主程序
                   md5.text     获取文件md5十六进制字符串
                   README.md    项目说明文件       

5. 贡献指南
     ```bash
     1.Fork项目
     2.创建新分支
     3.提交代码
     4.提交 Pull Request

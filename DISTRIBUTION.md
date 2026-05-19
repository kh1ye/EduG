# EduGenius 分发包使用说明

本压缩包为**精简源码版**，已排除依赖、构建缓存和本地数据，体积较小。解压后需按下列步骤安装依赖并配置 API 密钥。

## 环境要求

- Node.js 18+（推荐 20 LTS）
- Python 3.10+（推荐 3.11）
- 阿里云 DashScope API Key（用于 AI 与向量嵌入）

## 快速启动（Windows）

### 1. 解压到任意目录

例如：`D:\EduGenius`

### 2. 配置环境变量

```powershell
# 复制示例配置
copy .env.example .env.local
copy api\.env.example api\.env
```

编辑 `api\.env`，填入：

```env
DASHSCOPE_API_KEY=你的密钥
JWT_SECRET_KEY=任意随机长字符串
```

编辑 `.env.local`（可选）：

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

### 3. 安装依赖

**后端（在 `api` 目录）：**

```powershell
cd api
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

**前端（在项目根目录）：**

```powershell
npm install
```

### 4. 启动服务

开两个终端：

**终端 1 - 后端：**

```powershell
cd api
.\venv\Scripts\activate
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**终端 2 - 前端：**

```powershell
npm run dev
```

浏览器访问：http://localhost:3000

### 5. 使用流程

1. 注册 / 登录账号  
2. 进入「文档管理」上传 PDF / DOCX / PPTX 等教材  
3. 等待文档处理完成（状态为「已处理」）  
4. 点击「开始学习」进入 AI 辅导  

## 不包含的内容（需自行生成）

| 目录 | 说明 |
|------|------|
| `node_modules/` | 执行 `npm install` 生成 |
| `api/venv/` | 执行 `python -m venv venv` + `pip install` 生成 |
| `api/uploads/` | 上传文档后自动创建 |
| `api/chroma_db/` | 文档向量化后自动创建（RAG） |
| `api/edugenius.db` | 首次启动后自动创建 |

## 常见问题

**无法连接后端**  
确认后端在 8000 端口运行，且 `.env.local` 中 `NEXT_PUBLIC_API_URL` 正确。

**文档上传后一直处理中**  
查看后端终端报错；扫描版 PDF 可能需 OCR，纯图片 PDF 无法提取文字。

**AI 无响应**  
检查 `api\.env` 中 `DASHSCOPE_API_KEY` 是否有效、有余额。

更详细说明见项目内 `SETUP_GUIDE.md`、`README.md`。

# 📋 Site Survey Form (Streamlit)

A web-based Site Survey Form for documenting installation details and generating a downloadable PDF report.

## 🚀 Features

- Equipment catalog with dimensions and images  
- Photo upload (up to 20 photos)  
- Contact, delivery, and installation details  
- Automatic PDF report generation (using FPDF2)  
- Download button for generated report  

## 🧑‍💻 Local Setup

```bash
pip install -r requirements.txt
streamlit run main.py
```

Then open: [http://localhost:8501](http://localhost:8501)

## ☁️ Deploy to Streamlit Cloud

1. Push this project to a **public GitHub repository**.
2. Go to [https://share.streamlit.io](https://share.streamlit.io).
3. Select your repo, branch, and set **Main file path** to `main.py`.
4. Streamlit will automatically install dependencies and provide a public URL.

## 📦 Folder Structure

```
.
├─ main.py
├─ requirements.txt
├─ .gitignore
├─ .streamlit/
│  ├─ config.toml
│  └─ secrets_template.toml
└─ images/
```

## 🧰 Notes

- PDF generation and image previews are handled in memory (no local file writes).
- `maxUploadSize` in `.streamlit/config.toml` controls upload limits (default 200 MB).
- The app runs securely on Streamlit Cloud; no sensitive data is stored.

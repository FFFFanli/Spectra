FROM e2bdev/code-interpreter:latest

# 预装所有数据分析所需的依赖，避免沙箱每次启动时动态 pip install 超时
RUN pip install --no-cache-dir \
    pandas \
    numpy \
    duckdb \
    plotly \
    kaleido \
    scikit-learn \
    statsmodels \
    scipy \
    openpyxl \
    matplotlib \
    seaborn \
    xlsxwriter \
    tabulate \
    reportlab \
    pypdf \
    pdfplumber

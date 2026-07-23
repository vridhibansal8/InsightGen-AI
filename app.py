import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from google import genai
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from sqlalchemy import create_engine, text, inspect
from urllib.parse import quote_plus

# ==================================================
# PAGE CONFIG
# ==================================================

st.set_page_config(
    page_title="InsightGenAI",
    page_icon="🚀",
    layout="wide"
)

# ==================================================
# PDF GENERATOR HELPER
# ==================================================
def create_pdf(report_text):
    pdf_filename = "insightgenai_analyst_report.pdf"
    doc = SimpleDocTemplate(pdf_filename, pagesize=letter,
                            rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'PDFTitle', parent=styles['Heading1'], fontSize=20, leading=24, spaceAfter=20
    )
    heading_style = ParagraphStyle(
        'PDFHeading', parent=styles['Heading2'], fontSize=13, leading=16, spaceBefore=14, spaceAfter=6
    )
    body_style = ParagraphStyle(
        'PDFBody', parent=styles['Normal'], fontSize=10, leading=14, spaceAfter=6, alignment=TA_LEFT
    )

    story.append(Paragraph("InsightGenAI — Executive Insights Report", title_style))
    story.append(Spacer(1, 10))

    lines = report_text.split('\n')
    for line in lines:
        cleaned_line = line.replace('**', '').replace('*', '').strip()
        if not cleaned_line:
            continue
        
        if line.startswith('##'):
            story.append(Paragraph(cleaned_line, heading_style))
        else:
            story.append(Paragraph(cleaned_line, body_style))
            
    doc.build(story)
    return pdf_filename

# ==================================================
# HEADER
# ==================================================

st.title("🚀 InsightGenAI")
st.subheader("Automated Business Insights Generator")
st.write(
    "Upload any dataset or connect to a database (PostgreSQL, MySQL, SQL Server, Oracle, SQLite, or any custom SQLAlchemy-compatible source) and let InsightGenAI clean, prepare, and analyze data. "
    
)

# ==================================================
# DATA SOURCE SELECTION (FILE UPLOAD OR DATABASE)
# ==================================================

st.markdown("## 📂 Load Dataset")

data_source = st.radio(
    "Choose your data source:",
    ["📁 Upload File", "🗄️ Connect to Database"],
    horizontal=True
)

uploaded_file = None
source_identifier = None

# ------------------------------------------
# OPTION 1: FILE UPLOAD
# ------------------------------------------
if data_source == "📁 Upload File":
    uploaded_file = st.file_uploader(
        "Supported Formats: CSV, Excel, JSON, TXT",
        type=["csv", "xlsx", "xls", "json", "txt"]
    )
    if uploaded_file is not None:
        source_identifier = f"file::{uploaded_file.name}"

# ------------------------------------------
# OPTION 2: DATABASE CONNECTION (ANY ENGINE)
# ------------------------------------------
else:
    st.markdown("#### 🗄️ Database Connection")

    # Config per database engine: SQLAlchemy dialect/driver, default port,
    # and the pip package required for that driver.
    DB_ENGINE_CONFIG = {
        "PostgreSQL":            {"scheme": "postgresql+psycopg2", "default_port": "5432", "driver_pkg": "psycopg2-binary"},
        "MySQL / MariaDB":       {"scheme": "mysql+pymysql",       "default_port": "3306", "driver_pkg": "pymysql"},
        "SQL Server":            {"scheme": "mssql+pymssql",       "default_port": "1433", "driver_pkg": "pymssql"},
        "Oracle":                {"scheme": "oracle+oracledb",     "default_port": "1521", "driver_pkg": "oracledb"},
    }

    db_engine_choice = st.selectbox(
        "Database Type:",
        list(DB_ENGINE_CONFIG.keys()) + ["SQLite (local file)", "Other (paste full connection URI)"]
    )

    connection_uri = None
    connect_label = "🔌 Connect to Database"

    # ---- Standard client/server databases (Postgres, MySQL, SQL Server, Oracle) ----
    if db_engine_choice in DB_ENGINE_CONFIG:
        cfg = DB_ENGINE_CONFIG[db_engine_choice]
        st.caption(f"Requires the `{cfg['driver_pkg']}` package to be installed in this environment.")

        with st.form("db_connection_form"):
            dcol1, dcol2 = st.columns(2)
            with dcol1:
                db_host = st.text_input("Host", value=st.session_state.get("db_host", "localhost"))
                db_port = st.text_input("Port", value=st.session_state.get("db_port", cfg["default_port"]))
                db_name = st.text_input("Database Name", value=st.session_state.get("db_name", ""))
            with dcol2:
                db_user = st.text_input("Username", value=st.session_state.get("db_user", ""))
                db_password = st.text_input("Password", type="password", value=st.session_state.get("db_password", ""))
                db_schema_input = st.text_input(
                    "Schema (optional — leave blank to auto-detect)",
                    value=st.session_state.get("db_schema_input", "")
                )
            connect_submitted = st.form_submit_button(connect_label)

        if connect_submitted:
            st.session_state["db_host"] = db_host
            st.session_state["db_port"] = db_port
            st.session_state["db_name"] = db_name
            st.session_state["db_user"] = db_user
            st.session_state["db_password"] = db_password
            st.session_state["db_schema_input"] = db_schema_input
            connection_uri = (
                f"{cfg['scheme']}://{quote_plus(db_user)}:{quote_plus(db_password)}"
                f"@{db_host}:{db_port}/{db_name}"
            )

    # ---- SQLite: just a file path, no host/user/password ----
    elif db_engine_choice == "SQLite (local file)":
        st.caption("Point to a `.db` / `.sqlite` file already accessible on this machine, or upload one below.")
        sqlite_mode = st.radio("SQLite source:", ["File path on server", "Upload .db/.sqlite file"], horizontal=True)

        if sqlite_mode == "File path on server":
            sqlite_path = st.text_input("Database file path", value=st.session_state.get("sqlite_path", ""))
            if st.button(connect_label):
                st.session_state["sqlite_path"] = sqlite_path
                connection_uri = f"sqlite:///{sqlite_path}"
        else:
            sqlite_file = st.file_uploader("Upload SQLite database file", type=["db", "sqlite", "sqlite3"])
            if sqlite_file is not None and st.button(connect_label):
                temp_path = f"/tmp/{sqlite_file.name}"
                with open(temp_path, "wb") as f:
                    f.write(sqlite_file.getbuffer())
                st.session_state["sqlite_path"] = temp_path
                connection_uri = f"sqlite:///{temp_path}"

    # ---- Fully custom SQLAlchemy connection string ----
    else:
        st.caption(
            "Paste any valid SQLAlchemy connection URI, e.g. "
            "`postgresql+psycopg2://user:pass@host:5432/dbname` or "
            "`snowflake://user:pass@account/database/schema`."
        )
        custom_uri_input = st.text_input(
            "Connection URI",
            value=st.session_state.get("custom_uri_input", ""),
            type="password"
        )
        if st.button(connect_label):
            st.session_state["custom_uri_input"] = custom_uri_input
            connection_uri = custom_uri_input

    # ---- Establish / test the connection ----
    if connection_uri:
        try:
            engine = create_engine(connection_uri)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            st.session_state["db_engine"] = engine
            st.session_state["db_connected"] = True
            st.session_state["db_engine_choice"] = db_engine_choice
            # Clear any previously loaded table when a new connection is made
            st.session_state.pop("db_loaded_df", None)
            st.session_state.pop("db_source_key", None)
            st.success("✅ Connected to database successfully.")
        except Exception as conn_error:
            st.session_state["db_connected"] = False
            st.session_state.pop("db_engine", None)
            st.error(f"❌ Connection failed: {conn_error}")

    # ---- Browse schemas/tables and load data (dialect-agnostic via SQLAlchemy inspector) ----
    if st.session_state.get("db_connected") and "db_engine" in st.session_state:
        try:
            insp = inspect(st.session_state["db_engine"])

            schema_names = insp.get_schema_names()
            forced_schema = st.session_state.get("db_schema_input", "").strip()

            if forced_schema:
                selected_schema = forced_schema
            elif len(schema_names) > 1:
                default_schema = insp.default_schema_name
                default_index = schema_names.index(default_schema) if default_schema in schema_names else 0
                selected_schema = st.selectbox("Schema / Database:", schema_names, index=default_index)
            else:
                selected_schema = schema_names[0] if schema_names else None

            table_names = insp.get_table_names(schema=selected_schema)
            view_names = insp.get_view_names(schema=selected_schema) if hasattr(insp, "get_view_names") else []
            all_objects = sorted(table_names + view_names)

            if all_objects:
                st.markdown("#### 📋 Choose Data to Load")

                query_mode = st.radio(
                    "How do you want to pull data?",
                    ["Single Table", "🧩 Visual Query Builder", "✏️ Custom SQL Query"],
                    horizontal=True
                )

                selected_table = None
                custom_query = None

                def _qualify(t):
                    return f"{selected_schema}.{t}" if selected_schema else t

                # ---- MODE 1: Single table, no SQL needed ----
                if query_mode == "Single Table":
                    selected_table = st.selectbox(
                        "Select a table or view:",
                        options=["-- Select a Table --"] + all_objects
                    )

                # ---- MODE 2: Visual builder — join (auto or manual), filter, aggregate, sort, limit ----
                elif query_mode == "🧩 Visual Query Builder":
                    selected_tables_multi = st.multiselect(
                        "Select one or more tables:", options=all_objects
                    )

                    if len(selected_tables_multi) >= 1:
                        # Column metadata per table (name + type), dialect-agnostic via inspector
                        cols_map = {}
                        for tbl in selected_tables_multi:
                            try:
                                cols_map[tbl] = insp.get_columns(tbl, schema=selected_schema)
                            except Exception:
                                cols_map[tbl] = []

                        base_table = selected_tables_multi[0]
                        joined_tables = {base_table}
                        join_clauses = []  # (new_table, new_cols, existing_table, existing_cols, join_type)

                        # ---- JOINS: auto-detect via foreign keys, fall back to manual ----
                        if len(selected_tables_multi) >= 2:
                            st.markdown("##### 🔗 Table Relationships")
                            fk_map = {}
                            for tbl in selected_tables_multi:
                                try:
                                    fk_map[tbl] = insp.get_foreign_keys(tbl, schema=selected_schema)
                                except Exception:
                                    fk_map[tbl] = []

                            remaining = selected_tables_multi[1:]
                            for tbl in remaining:
                                found = None
                                for fk in fk_map.get(tbl, []):
                                    if fk.get("referred_table") in joined_tables:
                                        found = (tbl, fk["constrained_columns"], fk["referred_table"], fk["referred_columns"])
                                        break
                                if not found:
                                    for jt in joined_tables:
                                        for fk in fk_map.get(jt, []):
                                            if fk.get("referred_table") == tbl:
                                                found = (tbl, fk["referred_columns"], jt, fk["constrained_columns"])
                                                break
                                        if found:
                                            break

                                jcol1, jcol2, jcol3, jcol4 = st.columns([1.3, 1, 1, 1])
                                if found:
                                    new_t, new_cols, existing_t, existing_cols = found
                                    with jcol1:
                                        st.markdown(f"**{new_t}** ↔ **{existing_t}**")
                                        st.caption(f"Auto-detected via foreign key: `{existing_t}.{existing_cols[0]} = {new_t}.{new_cols[0]}`")
                                    with jcol2:
                                        pass
                                    with jcol3:
                                        pass
                                    with jcol4:
                                        join_type = st.selectbox(
                                            "Join type", ["LEFT", "INNER", "RIGHT", "FULL OUTER"],
                                            key=f"jtype_{tbl}"
                                        )
                                    join_clauses.append((new_t, new_cols, existing_t, existing_cols, join_type))
                                    joined_tables.add(tbl)
                                else:
                                    st.warning(f"⚠️ No foreign key detected for **{tbl}** — set the join manually:")
                                    with jcol1:
                                        join_to = st.selectbox(f"Join '{tbl}' to:", options=sorted(joined_tables), key=f"jointo_{tbl}")
                                    with jcol2:
                                        left_col = st.selectbox(
                                            f"Column in '{join_to}'",
                                            options=[c["name"] for c in cols_map.get(join_to, [])],
                                            key=f"leftcol_{tbl}"
                                        )
                                    with jcol3:
                                        right_col = st.selectbox(
                                            f"Column in '{tbl}'",
                                            options=[c["name"] for c in cols_map.get(tbl, [])],
                                            key=f"rightcol_{tbl}"
                                        )
                                    with jcol4:
                                        join_type = st.selectbox(
                                            "Join type", ["LEFT", "INNER", "RIGHT", "FULL OUTER"],
                                            key=f"jtype_{tbl}"
                                        )
                                    if left_col and right_col:
                                        join_clauses.append((tbl, [right_col], join_to, [left_col], join_type))
                                        joined_tables.add(tbl)

                        # ---- COLUMN SELECTION ----
                        st.markdown("##### 📐 Columns to Include")
                        all_qualified_cols = []  # list of (table, column) actually selected
                        for tbl in selected_tables_multi:
                            available = [c["name"] for c in cols_map.get(tbl, [])]
                            with st.expander(f"Columns from '{tbl}'", expanded=(len(selected_tables_multi) == 1)):
                                picked = st.multiselect(
                                    f"Include from {tbl}:", options=available, default=available, key=f"cols_{tbl}"
                                )
                            for c in picked:
                                all_qualified_cols.append((tbl, c))

                        # ---- AGGREGATION (optional) ----
                        st.markdown("##### 🧮 Group & Aggregate (optional)")
                        use_aggregation = st.checkbox("Group rows and apply an aggregate function")
                        group_by_cols = []
                        agg_cols = []
                        agg_func = "SUM"
                        if use_aggregation and all_qualified_cols:
                            col_labels = [f"{t}.{c}" for t, c in all_qualified_cols]
                            acol1, acol2 = st.columns(2)
                            with acol1:
                                group_by_cols = st.multiselect("Group by:", options=col_labels)
                            with acol2:
                                agg_cols = st.multiselect(
                                    "Columns to aggregate:",
                                    options=[l for l in col_labels if l not in group_by_cols]
                                )
                            agg_func = st.selectbox("Aggregate function:", ["SUM", "AVG", "COUNT", "MIN", "MAX"])

                        # ---- FILTERS (WHERE) ----
                        st.markdown("##### 🔍 Filters (optional)")
                        num_filters = st.number_input("Number of filter conditions:", min_value=0, max_value=5, value=0, step=1)
                        filter_clauses = []
                        col_labels_all = [f"{t}.{c}" for t, c in all_qualified_cols]
                        for i in range(int(num_filters)):
                            fcol1, fcol2, fcol3 = st.columns([1.5, 1, 1.5])
                            with fcol1:
                                fcol = st.selectbox("Column", options=col_labels_all, key=f"filtcol_{i}")
                            with fcol2:
                                fop = st.selectbox(
                                    "Operator", ["=", "!=", ">", "<", ">=", "<=", "LIKE", "IS NULL", "IS NOT NULL"],
                                    key=f"filtop_{i}"
                                )
                            with fcol3:
                                fval = "" if fop in ("IS NULL", "IS NOT NULL") else st.text_input("Value", key=f"filtval_{i}")
                            if fcol:
                                if fop in ("IS NULL", "IS NOT NULL"):
                                    filter_clauses.append(f"{fcol} {fop}")
                                elif fop == "LIKE":
                                    filter_clauses.append(f"{fcol} LIKE '%{fval}%'")
                                else:
                                    try:
                                        float(fval)
                                        filter_clauses.append(f"{fcol} {fop} {fval}")
                                    except (ValueError, TypeError):
                                        filter_clauses.append(f"{fcol} {fop} '{fval}'")

                        # ---- SORT & LIMIT ----
                        st.markdown("##### ↕️ Sort & Limit")
                        scol1, scol2, scol3 = st.columns([1.5, 1, 1])
                        with scol1:
                            sort_col = st.selectbox("Sort by:", options=["(none)"] + col_labels_all)
                        with scol2:
                            sort_dir = st.selectbox("Direction:", ["ASC", "DESC"])
                        with scol3:
                            row_limit = st.number_input("Limit rows:", min_value=1, max_value=100000, value=1000, step=100)

                        # ---- BUILD SQL ----
                        if use_aggregation and (group_by_cols or agg_cols):
                            select_parts = list(group_by_cols) + [f"{agg_func}({c}) AS {c.split('.')[-1]}_{agg_func.lower()}" for c in agg_cols]
                            select_clause = ", ".join(select_parts) if select_parts else "*"
                        else:
                            select_clause = ", ".join(col_labels_all) if col_labels_all else "*"

                        sql_lines = [f"SELECT {select_clause}", f"FROM {_qualify(base_table)}"]
                        for new_t, new_cols, existing_t, existing_cols, join_type in join_clauses:
                            conds = " AND ".join(f"{existing_t}.{ec} = {new_t}.{nc}" for nc, ec in zip(new_cols, existing_cols))
                            sql_lines.append(f"{join_type} JOIN {_qualify(new_t)} ON {conds}")
                        if filter_clauses:
                            sql_lines.append("WHERE " + " AND ".join(filter_clauses))
                        if use_aggregation and group_by_cols:
                            sql_lines.append("GROUP BY " + ", ".join(group_by_cols))
                        if sort_col != "(none)":
                            sql_lines.append(f"ORDER BY {sort_col} {sort_dir}")
                        sql_lines.append(f"LIMIT {int(row_limit)}")
                        generated_sql = "\n".join(sql_lines)

                        st.markdown("##### 🧾 Generated SQL")
                        st.caption("Review and tweak if needed before loading — this is a starting point, not locked in.")
                        custom_query = st.text_area("Generated query:", value=generated_sql, height=200)
                    else:
                        st.info("ℹ️ Select at least one table to begin.")

                # ---- MODE 3: Fully custom SQL ----
                else:
                    custom_query = st.text_area(
                        "Enter SQL query:", value="SELECT * FROM your_table LIMIT 1000", height=100
                    )

                if st.button("📥 Load Data From Database"):
                    try:
                        loaded_df = None
                        source_key = None

                        if query_mode in ("🧩 Visual Query Builder", "✏️ Custom SQL Query") and custom_query and custom_query.strip():
                            loaded_df = pd.read_sql(text(custom_query), st.session_state["db_engine"])
                            source_key = f"db::query::{hash(custom_query)}"
                        elif query_mode == "Single Table" and selected_table and selected_table != "-- Select a Table --":
                            loaded_df = pd.read_sql_table(
                                selected_table, st.session_state["db_engine"], schema=selected_schema
                            )
                            source_key = f"db::{st.session_state.get('db_engine_choice')}::{selected_schema}::{selected_table}"
                        else:
                            st.warning("⚠️ Please select a table, build a query, or enter a custom SQL query.")

                        if loaded_df is not None:
                            st.session_state["db_loaded_df"] = loaded_df
                            st.session_state["db_source_key"] = source_key
                            st.success(f"✅ Loaded {len(loaded_df):,} rows from the database.")
                    except Exception as query_error:
                        st.error(f"❌ Failed to load data: {query_error}")
            else:
                st.info("ℹ️ No tables or views found for this connection.")
        except Exception as list_error:
            st.error(f"❌ Could not list tables: {list_error}")

    if st.session_state.get("db_loaded_df") is not None:
        source_identifier = st.session_state.get("db_source_key")
        with st.expander("👀 Preview of data loaded from database", expanded=False):
            st.dataframe(st.session_state["db_loaded_df"].head(), use_container_width=True)

# ==================================================
# PROCESS DATASET (SHARED BY BOTH SOURCES FROM HERE ON)
# ==================================================

data_is_ready = (uploaded_file is not None) or (
    data_source == "🗄️ Connect to Database"
    and st.session_state.get("db_loaded_df") is not None
)

if data_is_ready:
    try:
        # ------------------------------------------
        # LOAD & INITIALIZE PERSISTENT STATE
        # ------------------------------------------
        if "current_file" not in st.session_state or st.session_state["current_file"] != source_identifier:
            if uploaded_file is not None:
                if uploaded_file.name.endswith(".csv"):
                    st.session_state["raw_df"] = pd.read_csv(uploaded_file)
                elif uploaded_file.name.endswith((".xlsx", ".xls")):
                    st.session_state["raw_df"] = pd.read_excel(uploaded_file)
                elif uploaded_file.name.endswith(".json"):
                    st.session_state["raw_df"] = pd.read_json(uploaded_file)
                elif uploaded_file.name.endswith(".txt"):
                    st.session_state["raw_df"] = pd.read_csv(uploaded_file)
            else:
                # Data source is the connected database
                st.session_state["raw_df"] = st.session_state["db_loaded_df"]

            st.session_state["current_file"] = source_identifier
            st.session_state["text_replacements"] = {}
            if "cleaned_dataset_df" in st.session_state:
                del st.session_state["cleaned_dataset_df"]
            if "computed_graph_findings" in st.session_state:
                del st.session_state["computed_graph_findings"]
            if "ai_report_markdown" in st.session_state:
                del st.session_state["ai_report_markdown"]
            st.session_state["fe_log"] = []
            st.session_state["chat_history"] = []
            st.session_state["outlier_treated"] = False

        df = st.session_state["raw_df"].copy()

        # ------------------------------------------
        # DATASET PREVIEW
        # ------------------------------------------
        st.markdown("## 👀 Dataset Preview")
        st.dataframe(df.head(), use_container_width=True)

        # ------------------------------------------
        # DATASET OVERVIEW
        # ------------------------------------------
        st.markdown("## 📊 Dataset Overview")

        total_rows = df.shape[0]
        total_columns = df.shape[1]
        total_missing = int(df.isnull().sum().sum())
        total_duplicates = int(df.duplicated().sum())

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Rows", total_rows)
        col2.metric("Columns", total_columns)
        col3.metric("Missing Values", total_missing)
        col4.metric("Duplicate Rows", total_duplicates)

        # ------------------------------------------
        # IN-PLACE DATA QUALITY SUMMARY & EDITING
        # ------------------------------------------
        st.markdown("## 📋 Data Quality Analysis")
        st.caption("Double-click any cell in **Column Name** to rename it, or click **Data Type** to select a new type from the dropdown menu.")

        original_columns = list(df.columns)
        
        current_dtypes = []
        for t in df.dtypes.values:
            t_str = str(t)
            if t_str.startswith("object"):
                current_dtypes.append("str")
            else:
                current_dtypes.append(t_str)

        target_options = sorted(list(set(current_dtypes + ["str", "int64", "float64", "bool", "datetime64[ns]"])))

        quality_base_df = pd.DataFrame({
            "Column Name": df.columns,
            "Data Type": current_dtypes,
            "Unique Values": df.nunique(dropna=True).values,
            "Non-Null Count": df.notnull().sum().values,
            "Missing Values": df.isnull().sum().values,
            "Missing %": ((df.isnull().sum().values / len(df)) * 100).round(2)
        })

        edited_quality_df = st.data_editor(
            quality_base_df,
            hide_index=True,
            use_container_width=True,
            disabled=["Non-Null Count", "Missing Values", "Missing %"],
            column_config={
                "Column Name": st.column_config.TextColumn("Column Name", required=True),
                "Data Type": st.column_config.SelectboxColumn("Data Type", options=target_options, required=True)
            },
            key="data_quality_editor"
        )

        rename_dict = {}
        type_cast_dict = {}

        for idx, row in edited_quality_df.iterrows():
            orig = original_columns[idx]
            new = row["Column Name"]
            target_type = row["Data Type"]
            current_type = current_dtypes[idx]

            if new and new != orig:
                rename_dict[orig] = new
                active_col_name = new
            else:
                active_col_name = orig

            if target_type != current_type:
                type_cast_dict[active_col_name] = target_type

        if rename_dict:
            df = df.rename(columns=rename_dict)

        if type_cast_dict:
            for column, target in type_cast_dict.items():
                try:
                    if target == "datetime64[ns]":
                        df[column] = pd.to_datetime(df[column], errors="coerce")
                    elif target == "str":
                        df[column] = df[column].astype(object)
                    else:
                        df[column] = df[column].astype(target)
                except Exception as cast_error:
                    st.warning(f"⚠️ Could not cast column '{column}' to {target}: {cast_error}")

        # ------------------------------------------
        # DATA HEALTH SCORE & MISSINGNESS PATTERN
        # ------------------------------------------
        st.markdown("## 🩺 Data Health Score")
        st.caption("A quick diagnostic before trusting a dataset — completeness, uniqueness, and structural quality at a glance.")

        completeness_score = round((1 - (df.isnull().sum().sum() / (df.shape[0] * df.shape[1]))) * 100, 1) if df.shape[0] * df.shape[1] > 0 else 100
        uniqueness_score = round((1 - (df.duplicated().sum() / df.shape[0])) * 100, 1) if df.shape[0] > 0 else 100
        constant_cols = sum(1 for c in df.columns if df[c].nunique(dropna=False) == 1)
        structure_score = round((1 - (constant_cols / df.shape[1])) * 100, 1) if df.shape[1] > 0 else 100
        overall_health = round((completeness_score + uniqueness_score + structure_score) / 3, 1)

        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Overall Health Score", f"{overall_health}%")
        h2.metric("Completeness", f"{completeness_score}%")
        h3.metric("Uniqueness (Non-duplicate rows)", f"{uniqueness_score}%")
        h4.metric("Structural Quality", f"{structure_score}%")

        
        # ------------------------------------------
        # DROP COLUMN RECOMMENDATIONS
        # ------------------------------------------
        st.markdown("## 🗑️ Drop Column Recommendations")

        recommendations = []
        auto_drop_defaults = []  

        for col in df.columns:
            missing_pct = (df[col].isnull().sum() / len(df)) * 100

            if missing_pct > 80:
                auto_drop_defaults.append(col)  
                recommendations.append({
                    "Column": col,
                    "Missing %": round(missing_pct, 2),
                    "Reason to Drop": f"{round(missing_pct,2)}% missing values"
                })
            elif df[col].nunique(dropna=False) == 1:
                recommendations.append({
                    "Column": col,
                    "Missing %": round(missing_pct, 2),
                    "Reason to Drop": "Only one unique value"
                })
            elif col.lower().endswith("_id") or col.lower() == "id" or "id" in col.lower():
                recommendations.append({
                    "Column": col,
                    "Missing %": round(missing_pct, 2),
                    "Reason to Drop": "Identifier column"
                })

        columns = list(df.columns)
        for i in range(len(columns)):
            for j in range(i + 1, len(columns)):
                col1_name = columns[i]
                col2_name = columns[j]
                if df[col1_name].equals(df[col2_name]):
                    recommendations.append({
                        "Column": col2_name,
                        "Missing %": round((df[col2_name].isnull().sum() / len(df)) * 100, 2),
                        "Reason to Drop": f"Duplicate of '{col1_name}'"
                    })

        if recommendations:
            rec_df = pd.DataFrame(recommendations)
            rec_df = rec_df.sort_values(by="Missing %", ascending=False)
            st.dataframe(rec_df[["Column", "Reason to Drop"]], use_container_width=True)
        else:
            st.success("✅ No columns recommended for dropping.")

        # ------------------------------------------
        # SELECT COLUMNS TO DROP
        # ------------------------------------------
        st.markdown("## ✂️ Select Columns to Drop")

        auto_drop_defaults = [rename_dict.get(c, c) for c in auto_drop_defaults]
        columns_to_drop = st.multiselect(
            "Select columns to drop:",
            options=df.columns.tolist(),
            default=auto_drop_defaults
        )

        if columns_to_drop:
            df = df.drop(columns=columns_to_drop, errors="ignore")
            st.success(f"✅ {len(columns_to_drop)} column(s) dropped successfully.")

        # ------------------------------------------
        # STANDARDIZE CATEGORICAL VALUES
        # ------------------------------------------
        st.markdown("---")
        st.markdown("## 🔄 Standardize Text & Category Values")

        categorical_cols = []
        for c in df.columns:
            if pd.api.types.is_string_dtype(df[c]) or pd.api.types.is_object_dtype(df[c]):
                if not pd.api.types.is_numeric_dtype(df[c]):
                    if not any(k in c.lower() for k in ["date", "time", "joining", "timestamp", "release"]):
                        categorical_cols.append(c)

        if categorical_cols:
            selected_merge_col = st.selectbox("Choose a column to check for inconsistent values:", options=["-- Select a Column --"] + categorical_cols)

            if selected_merge_col != "-- Select a Column --":
                unique_vals = sorted([str(v) for v in df[selected_merge_col].dropna().unique()])

                if f"map_{selected_merge_col}" not in st.session_state:
                    st.session_state[f"map_{selected_merge_col}"] = pd.DataFrame({
                        "Current Value": unique_vals,
                        "Standardized Value": unique_vals  
                    })

                current_map_df = st.session_state[f"map_{selected_merge_col}"]
                current_map_df = current_map_df[current_map_df["Current Value"].isin(unique_vals)]
                
                edited_mapping_df = st.data_editor(
                    current_map_df,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["Current Value"],
                    key=f"editor_widget_{selected_merge_col}"
                )

                st.session_state[f"map_{selected_merge_col}"] = edited_mapping_df

                value_replacement_map = {}
                for _, row in edited_mapping_df.iterrows():
                    curr = row["Current Value"]
                    std = row["Standardized Value"]
                    if std and std != curr:
                        value_replacement_map[curr] = std

                st.session_state["text_replacements"][selected_merge_col] = value_replacement_map

            for col_to_patch, replacements in st.session_state["text_replacements"].items():
                if col_to_patch in df.columns and replacements:
                    df[col_to_patch] = df[col_to_patch].astype(str).replace(replacements)
        else:
            st.info("ℹ️ No categorical columns found to standardize.")

        # ==================================================
        # ROW CLEANING PIPELINE
        # ==================================================
        st.markdown("---")
        

        if st.button("🚀 Run Data Cleaning"):
            cleaned_df = df.copy()
            initial_rows = cleaned_df.shape[0]

            cleaned_df = cleaned_df.drop_duplicates()
            dropped_dups = initial_rows - cleaned_df.shape[0]

            if cleaned_df.shape[1] > 0:
                row_missing_pct = cleaned_df.isnull().sum(axis=1) / cleaned_df.shape[1]
                high_missing_mask = row_missing_pct > 0.80
                dropped_missing_rows = high_missing_mask.sum()
                cleaned_df = cleaned_df[~high_missing_mask]
            else:
                dropped_missing_rows = 0

            rows_with_any_missing = cleaned_df.isnull().any(axis=1).sum()

            st.markdown("### 📊 Data After Cleaning")
            
            c1, c2, c3, c4 = st.columns(4)

            c1.metric("Rows After Cleaning", cleaned_df.shape[0])
            c2.metric("Columns After Cleaning", cleaned_df.shape[1])
            c3.metric("Duplicates Removed", int(dropped_dups))
            c4.metric("Missing Rows Removed", int(dropped_missing_rows))

            for col in cleaned_df.columns:
                missing_count = cleaned_df[col].isnull().sum()
                if missing_count > 0:
                    if pd.api.types.is_numeric_dtype(cleaned_df[col]):
                        median_val = cleaned_df[col].median()
                        cleaned_df[col] = cleaned_df[col].fillna(median_val if pd.notnull(median_val) else 0)
                    elif pd.api.types.is_datetime64_any_dtype(cleaned_df[col]):
                        cleaned_df[col] = cleaned_df[col].ffill().bfill()
                    else:
                        col_mode = cleaned_df[col].mode()
                        cleaned_df[col] = cleaned_df[col].fillna(col_mode[0] if not col_mode.empty else "Not Provided")
            
            if cleaned_df.isnull().sum().sum() > 0:
                cleaned_df = cleaned_df.ffill().bfill()

            st.success("🎉 Data Cleaning Completed Successfully")
            st.markdown("### 👀 Final Cleaned Dataset")
            st.dataframe(cleaned_df.head(), use_container_width=True)

            st.markdown("### 📉 Cleaned Data Statistical Summary")
            summary_df = cleaned_df.describe(include='all').astype(str).fillna("-")
            st.dataframe(summary_df, use_container_width=True)

            st.session_state["cleaned_dataset_df"] = cleaned_df

        # ==================================================
        # STAGE: OUTLIER DETECTION & HANDLING
        # ==================================================
        if "cleaned_dataset_df" in st.session_state:
            st.markdown("---")
            st.markdown("## 🎯 Outlier Detection & Handling")
            st.write("Detect statistical outliers in numeric columns using the IQR method (the standard analyst approach) and choose how to treat them before analysis.")

            outlier_base_df = st.session_state["cleaned_dataset_df"].copy()
            numeric_cols_for_outliers = [
                c for c in outlier_base_df.columns
                if pd.api.types.is_numeric_dtype(outlier_base_df[c]) and outlier_base_df[c].dtype != 'bool'
            ]

            if numeric_cols_for_outliers:
                outlier_summary = []
                bounds_map = {}
                for col in numeric_cols_for_outliers:
                    q1 = outlier_base_df[col].quantile(0.25)
                    q3 = outlier_base_df[col].quantile(0.75)
                    iqr = q3 - q1
                    lower = q1 - 1.5 * iqr
                    upper = q3 + 1.5 * iqr
                    bounds_map[col] = (lower, upper)
                    outlier_count = int(((outlier_base_df[col] < lower) | (outlier_base_df[col] > upper)).sum())
                    outlier_pct = round((outlier_count / len(outlier_base_df)) * 100, 2) if len(outlier_base_df) else 0
                    outlier_summary.append({
                        "Column": col,
                        "Lower Bound": round(float(lower), 2),
                        "Upper Bound": round(float(upper), 2),
                        "Outlier Count": outlier_count,
                        "Outlier %": outlier_pct
                    })

                outlier_summary_df = pd.DataFrame(outlier_summary).sort_values(by="Outlier Count", ascending=False)
                st.dataframe(outlier_summary_df, use_container_width=True)

                cols_with_outliers = outlier_summary_df[outlier_summary_df["Outlier Count"] > 0]["Column"].tolist()

                if cols_with_outliers:
                    oc1, oc2 = st.columns([2, 1])
                    with oc1:
                        selected_outlier_cols = st.multiselect(
                            "Select columns to treat:",
                            options=cols_with_outliers,
                            default=cols_with_outliers
                        )
                    with oc2:
                        treatment_method = st.selectbox(
                            "Treatment Method:",
                            options=["Cap (Winsorize to IQR bounds)", "Remove Rows", "Leave As-Is"]
                        )

                    if st.button("🎯 Apply Outlier Treatment"):
                        treated_df = st.session_state["cleaned_dataset_df"].copy()

                        if treatment_method == "Cap (Winsorize to IQR bounds)":
                            for col in selected_outlier_cols:
                                lower, upper = bounds_map[col]
                                treated_df[col] = treated_df[col].clip(lower=lower, upper=upper)
                            st.success(f"✅ Capped outliers in {len(selected_outlier_cols)} column(s) to their IQR bounds.")

                        elif treatment_method == "Remove Rows":
                            mask = pd.Series(False, index=treated_df.index)
                            for col in selected_outlier_cols:
                                lower, upper = bounds_map[col]
                                mask = mask | (treated_df[col] < lower) | (treated_df[col] > upper)
                            rows_removed = int(mask.sum())
                            treated_df = treated_df[~mask]
                            st.success(f"✅ Removed {rows_removed} row(s) containing outliers.")

                        else:
                            st.info("ℹ️ No changes applied — outliers left as-is.")

                        st.session_state["cleaned_dataset_df"] = treated_df
                        st.session_state["outlier_treated"] = True
                        st.rerun()
                else:
                    st.success("✅ No significant outliers detected in numeric columns.")
            else:
                st.info("ℹ️ No numeric columns available for outlier detection.")

        # ==================================================
        # STAGE: FEATURE ENGINEERING & CALCULATED COLUMNS
        # ==================================================
        if "cleaned_dataset_df" in st.session_state:
            st.markdown("---")
            st.markdown("## 🧮 Feature Engineering & Calculated Columns")
            

            if "fe_log" not in st.session_state:
                st.session_state["fe_log"] = []

            fe_df = st.session_state["cleaned_dataset_df"]

            fe_numeric_cols = [c for c in fe_df.columns if pd.api.types.is_numeric_dtype(fe_df[c]) and fe_df[c].dtype != 'bool']
            fe_datetime_cols = [c for c in fe_df.columns if pd.api.types.is_datetime64_any_dtype(fe_df[c])]
            fe_categorical_cols = [c for c in fe_df.columns if not pd.api.types.is_numeric_dtype(fe_df[c]) and not pd.api.types.is_datetime64_any_dtype(fe_df[c])]

            fe_operation = st.selectbox(
                "Choose an operation:",
                [
                    "-- Select an Operation --",
                    "📅 Extract Date Parts (Year / Month / Quarter / Weekday)",
                    "➗ Ratio / Percentage Column",
                    "➖ Difference Column",
                    "📊 Growth % Between Two Columns",
                    "🏷️ Bin Numeric Column (Low / Medium / High)",
                    "🔗 Combine Text Columns"
                ]
            )

            if fe_operation == "📅 Extract Date Parts (Year / Month / Quarter / Weekday)":
                if fe_datetime_cols:
                    dt_col = st.selectbox("Select Date Column:", fe_datetime_cols)
                    parts = st.multiselect("Parts to extract:", ["Year", "Month", "Quarter", "Weekday", "Is_Weekend"], default=["Year", "Month"])
                    if st.button("➕ Add Date Feature Columns"):
                        new_cols = []
                        if "Year" in parts:
                            fe_df[f"{dt_col}_Year"] = fe_df[dt_col].dt.year
                            new_cols.append(f"{dt_col}_Year")
                        if "Month" in parts:
                            fe_df[f"{dt_col}_Month"] = fe_df[dt_col].dt.month
                            new_cols.append(f"{dt_col}_Month")
                        if "Quarter" in parts:
                            fe_df[f"{dt_col}_Quarter"] = fe_df[dt_col].dt.quarter
                            new_cols.append(f"{dt_col}_Quarter")
                        if "Weekday" in parts:
                            fe_df[f"{dt_col}_Weekday"] = fe_df[dt_col].dt.day_name()
                            new_cols.append(f"{dt_col}_Weekday")
                        if "Is_Weekend" in parts:
                            fe_df[f"{dt_col}_Is_Weekend"] = fe_df[dt_col].dt.dayofweek.isin([5, 6])
                            new_cols.append(f"{dt_col}_Is_Weekend")
                        st.session_state["cleaned_dataset_df"] = fe_df
                        st.session_state["fe_log"].extend(new_cols)
                        st.success(f"✅ Added: {', '.join(new_cols)}")
                        st.rerun()
                else:
                    st.info("ℹ️ No datetime columns available.")

            elif fe_operation == "➗ Ratio / Percentage Column":
                if len(fe_numeric_cols) >= 2:
                    num_col = st.selectbox("Numerator:", fe_numeric_cols, key="ratio_num")
                    den_col = st.selectbox("Denominator:", fe_numeric_cols, key="ratio_den")
                    new_col_name = st.text_input("New Column Name:", value=f"{num_col}_to_{den_col}_pct")
                    if st.button("➕ Add Ratio Column"):
                        fe_df[new_col_name] = (fe_df[num_col] / fe_df[den_col].replace(0, pd.NA)) * 100
                        st.session_state["cleaned_dataset_df"] = fe_df
                        st.session_state["fe_log"].append(new_col_name)
                        st.success(f"✅ Added column: {new_col_name}")
                        st.rerun()
                else:
                    st.info("ℹ️ Need at least 2 numeric columns.")

            elif fe_operation == "➖ Difference Column":
                if len(fe_numeric_cols) >= 2:
                    col_a = st.selectbox("Column A:", fe_numeric_cols, key="diff_a")
                    col_b = st.selectbox("Column B:", fe_numeric_cols, key="diff_b")
                    new_col_name = st.text_input("New Column Name:", value=f"{col_a}_minus_{col_b}")
                    if st.button("➕ Add Difference Column"):
                        fe_df[new_col_name] = fe_df[col_a] - fe_df[col_b]
                        st.session_state["cleaned_dataset_df"] = fe_df
                        st.session_state["fe_log"].append(new_col_name)
                        st.success(f"✅ Added column: {new_col_name}")
                        st.rerun()
                else:
                    st.info("ℹ️ Need at least 2 numeric columns.")

            elif fe_operation == "📊 Growth % Between Two Columns":
                if len(fe_numeric_cols) >= 2:
                    old_col = st.selectbox("Base / Previous Value Column:", fe_numeric_cols, key="growth_old")
                    new_col = st.selectbox("New / Current Value Column:", fe_numeric_cols, key="growth_new")
                    new_col_name = st.text_input("New Column Name:", value=f"{new_col}_growth_pct")
                    if st.button("➕ Add Growth % Column"):
                        fe_df[new_col_name] = ((fe_df[new_col] - fe_df[old_col]) / fe_df[old_col].replace(0, pd.NA)) * 100
                        st.session_state["cleaned_dataset_df"] = fe_df
                        st.session_state["fe_log"].append(new_col_name)
                        st.success(f"✅ Added column: {new_col_name}")
                        st.rerun()
                else:
                    st.info("ℹ️ Need at least 2 numeric columns.")

            elif fe_operation == "🏷️ Bin Numeric Column (Low / Medium / High)":
                if fe_numeric_cols:
                    bin_col = st.selectbox("Select Numeric Column to Bin:", fe_numeric_cols, key="bin_col")
                    new_col_name = st.text_input("New Column Name:", value=f"{bin_col}_Category")
                    if st.button("➕ Add Binned Column"):
                        try:
                            fe_df[new_col_name] = pd.qcut(fe_df[bin_col], q=3, labels=["Low", "Medium", "High"], duplicates="drop")
                        except Exception:
                            fe_df[new_col_name] = pd.cut(fe_df[bin_col], bins=3, labels=["Low", "Medium", "High"])
                        st.session_state["cleaned_dataset_df"] = fe_df
                        st.session_state["fe_log"].append(new_col_name)
                        st.success(f"✅ Added column: {new_col_name}")
                        st.rerun()
                else:
                    st.info("ℹ️ No numeric columns available.")

            elif fe_operation == "🔗 Combine Text Columns":
                if len(fe_categorical_cols) >= 2:
                    txt_a = st.selectbox("Column A:", fe_categorical_cols, key="combine_a")
                    txt_b = st.selectbox("Column B:", fe_categorical_cols, key="combine_b")
                    separator = st.text_input("Separator:", value=" - ")
                    new_col_name = st.text_input("New Column Name:", value=f"{txt_a}_{txt_b}_combined")
                    if st.button("➕ Add Combined Column"):
                        fe_df[new_col_name] = fe_df[txt_a].astype(str) + separator + fe_df[txt_b].astype(str)
                        st.session_state["cleaned_dataset_df"] = fe_df
                        st.session_state["fe_log"].append(new_col_name)
                        st.success(f"✅ Added column: {new_col_name}")
                        st.rerun()
                else:
                    st.info("ℹ️ Need at least 2 text/categorical columns.")

            if st.session_state["fe_log"]:
                st.caption(f"📌 Engineered columns added so far: {', '.join(st.session_state['fe_log'])}")
                st.dataframe(st.session_state["cleaned_dataset_df"].head(), use_container_width=True)

        # ==================================================
        # STAGE 7: EXPLORATORY DATA ANALYSIS (EDA)
        # Built the way a data analyst actually explores data:
        # distributions -> category breakdowns -> trends over time
        # -> correlations -> strongest relationships -> segment comparisons
        # ==================================================

        if "cleaned_dataset_df" in st.session_state:
            st.markdown("---")
            st.markdown("## 🔍 Exploratory Data Analysis (EDA)")
            

            if st.button("📊 Run Automated EDA"):
                st.session_state["trigger_eda_view"] = True

            if st.session_state.get("trigger_eda_view", False):
                active_eda_df = st.session_state["cleaned_dataset_df"].copy()

                # Rebuilt fresh every run — holds a plain-English description of
                # every chart currently on screen, with its actual numbers, so
                # the chatbot can answer "what does this chart show?" accurately.
                st.session_state["chart_log"] = []

                def log_chart(description):
                    st.session_state["chart_log"].append(description)

                # ------------------------------------------
                # Feature Separation Matrix
                # ------------------------------------------
                numerical_cols = []
                categorical_cols_detected = []
                datetime_cols = []

                for col in active_eda_df.columns:
                    col_lower = col.lower()
                    if any(keyword in col_lower for keyword in ["date", "time", "joining", "timestamp", "release"]) or pd.api.types.is_datetime64_any_dtype(active_eda_df[col]):
                        if not pd.api.types.is_datetime64_any_dtype(active_eda_df[col]):
                            try:
                                active_eda_df[col] = pd.to_datetime(active_eda_df[col], errors='coerce')
                            except:
                                pass
                        datetime_cols.append(col)
                        continue

                    if pd.api.types.is_numeric_dtype(active_eda_df[col]) and active_eda_df[col].dtype != 'bool':
                        if col_lower.endswith("id") or col_lower == "id":
                            categorical_cols_detected.append(col)
                        else:
                            numerical_cols.append(col)
                    else:
                        categorical_cols_detected.append(col)

                # Performance: render heavy point-based charts (histograms, scatter)
                # on a sample for large datasets. All stats/metrics/aggregations still
                # use the full dataset — only the raw plotted points are sampled.
                PLOT_SAMPLE_LIMIT = 5000
                if len(active_eda_df) > PLOT_SAMPLE_LIMIT:
                    plot_df = active_eda_df.sample(PLOT_SAMPLE_LIMIT, random_state=42)
                    st.info(f"⚡ Dataset has {len(active_eda_df):,} rows — charts are rendered on a random {PLOT_SAMPLE_LIMIT:,}-row sample for speed. All statistics shown are calculated on the full dataset.")
                else:
                    plot_df = active_eda_df

                # ------------------------------------------
                # SECTION 1: NUMERIC DISTRIBUTIONS
                # ------------------------------------------
                st.markdown("### 📐 Numeric Feature Distributions")
                st.caption("Shape, spread, and outlier position of each numeric field — histogram with an attached box plot.")

                if numerical_cols:
                    display_numeric_cols = numerical_cols[:8]
                    if len(numerical_cols) > 8:
                        st.caption(f"Showing the first 8 of {len(numerical_cols)} numeric columns.")

                    for i in range(0, len(display_numeric_cols), 2):
                        row_cols = st.columns(2)
                        for j, col_name in enumerate(display_numeric_cols[i:i+2]):
                            with row_cols[j]:
                                fig = px.histogram(
                                    plot_df, x=col_name, marginal="box",
                                    title=f"Distribution of {col_name}"
                                )
                                st.plotly_chart(fig, use_container_width=True)
                                st.caption(
                                    f"Mean: {active_eda_df[col_name].mean():.2f} | "
                                    f"Median: {active_eda_df[col_name].median():.2f} | "
                                    f"Std Dev: {active_eda_df[col_name].std():.2f} | "
                                    f"Skew: {active_eda_df[col_name].skew():.2f}"
                                )
                                log_chart(
                                    f"Chart \"Distribution of {col_name}\" (histogram + box plot): "
                                    f"mean={active_eda_df[col_name].mean():.2f}, median={active_eda_df[col_name].median():.2f}, "
                                    f"min={active_eda_df[col_name].min():.2f}, max={active_eda_df[col_name].max():.2f}, "
                                    f"std dev={active_eda_df[col_name].std():.2f}, skew={active_eda_df[col_name].skew():.2f} "
                                    f"(skew>0 means a long tail of high values; skew<0 means a long tail of low values)."
                                )
                else:
                    st.info("ℹ️ No numeric columns detected.")

                # ------------------------------------------
                # SECTION 2: CATEGORICAL BREAKDOWNS
                # ------------------------------------------
                st.markdown("### 🔤 Categorical Feature Breakdown")
                st.caption("Frequency of each category — where volume concentrates and where it thins out.")

                if categorical_cols_detected:
                    plottable_cats = [c for c in categorical_cols_detected if active_eda_df[c].nunique(dropna=True) <= 40]
                    skipped_cats = [c for c in categorical_cols_detected if c not in plottable_cats]
                    display_cat_cols = plottable_cats[:6]

                    if display_cat_cols:
                        for i in range(0, len(display_cat_cols), 2):
                            row_cols = st.columns(2)
                            for j, col_name in enumerate(display_cat_cols[i:i+2]):
                                with row_cols[j]:
                                    vc = active_eda_df[col_name].astype(str).value_counts().head(15).reset_index()
                                    vc.columns = [col_name, "count"]
                                    fig = px.bar(vc, x=col_name, y="count", title=f"Frequency of {col_name}")
                                    st.plotly_chart(fig, use_container_width=True)
                                    top_items = ", ".join(f"{r[col_name]} ({r['count']})" for _, r in vc.head(5).iterrows())
                                    log_chart(f"Chart \"Frequency of {col_name}\" (bar chart of category counts): top values are {top_items}.")
                    if skipped_cats:
                        st.caption(f"⏭️ Skipped high-cardinality columns (too many unique values to chart clearly): {', '.join(skipped_cats)}")
                else:
                    st.info("ℹ️ No categorical columns detected.")

                # ------------------------------------------
                # SECTION 3: TRENDS OVER TIME
                # ------------------------------------------
                if datetime_cols:
                    st.markdown("### 📅 Trends Over Time")
                    st.caption("Volume and key metrics tracked month over month.")

                    for dt_col in datetime_cols[:2]:
                        valid_dates = active_eda_df[dt_col].dropna()
                        if valid_dates.empty:
                            continue

                        ts_data = active_eda_df.groupby(active_eda_df[dt_col].dt.to_period('M')).size().reset_index(name='count')
                        ts_data[dt_col] = ts_data[dt_col].astype(str)
                        st.plotly_chart(
                            px.bar(ts_data, x=dt_col, y='count', title=f"Record Volume by Month ({dt_col})"),
                            use_container_width=True
                        )
                        peak_row = ts_data.loc[ts_data['count'].idxmax()]
                        log_chart(
                            f"Chart \"Record Volume by Month ({dt_col})\" (bar chart): "
                            f"spans {ts_data[dt_col].iloc[0]} to {ts_data[dt_col].iloc[-1]}, "
                            f"peak month is {peak_row[dt_col]} with {int(peak_row['count'])} records."
                        )

                        if numerical_cols:
                            trend_metric = numerical_cols[0]
                            metric_trend = active_eda_df.groupby(active_eda_df[dt_col].dt.to_period('M'))[trend_metric].mean().reset_index()
                            metric_trend[dt_col] = metric_trend[dt_col].astype(str)
                            st.plotly_chart(
                                px.line(metric_trend, x=dt_col, y=trend_metric, markers=True,
                                        title=f"Average {trend_metric} Over Time"),
                                use_container_width=True
                            )
                            start_val = metric_trend[trend_metric].iloc[0]
                            end_val = metric_trend[trend_metric].iloc[-1]
                            direction = "increased" if end_val > start_val else ("decreased" if end_val < start_val else "stayed flat")
                            log_chart(
                                f"Chart \"Average {trend_metric} Over Time\" (line chart): "
                                f"{trend_metric} {direction} from {start_val:.2f} ({metric_trend[dt_col].iloc[0]}) "
                                f"to {end_val:.2f} ({metric_trend[dt_col].iloc[-1]})."
                            )

                # ------------------------------------------
                # SECTION 4: CORRELATION BETWEEN NUMERIC METRICS
                # ------------------------------------------
                if len(numerical_cols) >= 2:
                    st.markdown("### 🔗 How Numeric Metrics Relate to Each Other")
                    st.caption("Correlation heatmap — values near +1 or -1 indicate a strong relationship.")

                    corr_cols = numerical_cols[:12]
                    corr_matrix = active_eda_df[corr_cols].corr()
                    st.plotly_chart(px.imshow(corr_matrix, text_auto=".2f", aspect="auto", color_continuous_scale="RdBu_r", zmin=-1, zmax=1), use_container_width=True)

                    _corr_pairs_for_log = []
                    for i in range(len(corr_cols)):
                        for j in range(i + 1, len(corr_cols)):
                            v = corr_matrix.iloc[i, j]
                            if pd.notnull(v):
                                _corr_pairs_for_log.append((corr_cols[i], corr_cols[j], v))
                    _corr_pairs_for_log.sort(key=lambda x: abs(x[2]), reverse=True)
                    corr_summary = "; ".join(f"{a} vs {b}: {v:.2f}" for a, b, v in _corr_pairs_for_log[:5])
                    log_chart(f"Chart \"Correlation Heatmap\": strongest relationships are {corr_summary}.")

                    # ------------------------------------------
                    # SECTION 5: STRONGEST RELATIONSHIPS (manual trendline, no statsmodels needed)
                    # ------------------------------------------
                    st.markdown("### 🎯 Strongest Relationships")
                    st.caption("The most correlated numeric pairs, with a fitted trend line.")

                    corr_pairs = []
                    for i in range(len(corr_cols)):
                        for j in range(i + 1, len(corr_cols)):
                            val = corr_matrix.iloc[i, j]
                            if pd.notnull(val):
                                corr_pairs.append((corr_cols[i], corr_cols[j], val))

                    corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)
                    top_pairs = corr_pairs[:3]

                    if top_pairs:
                        for x_col, y_col, corr_val in top_pairs:
                            pair_df = plot_df[[x_col, y_col]].dropna()
                            if len(pair_df) < 2:
                                continue

                            fig = go.Figure()
                            fig.add_trace(go.Scatter(
                                x=pair_df[x_col], y=pair_df[y_col], mode="markers",
                                name="Data Points", marker=dict(opacity=0.6)
                            ))

                            # Manual linear trend fit (numpy only — no statsmodels dependency)
                            try:
                                slope, intercept = np.polyfit(pair_df[x_col], pair_df[y_col], 1)
                                x_range = np.linspace(pair_df[x_col].min(), pair_df[x_col].max(), 50)
                                y_fit = slope * x_range + intercept
                                fig.add_trace(go.Scatter(
                                    x=x_range, y=y_fit, mode="lines", name="Trend Line", line=dict(color="red")
                                ))
                            except Exception:
                                pass

                            fig.update_layout(title=f"{x_col} vs {y_col}  (correlation: {corr_val:.2f})",
                                               xaxis_title=x_col, yaxis_title=y_col)
                            st.plotly_chart(fig, use_container_width=True)
                            relationship = "move together (positive)" if corr_val > 0 else "move in opposite directions (negative)"
                            log_chart(
                                f"Chart \"{x_col} vs {y_col}\" (scatter with trend line): correlation={corr_val:.2f}, "
                                f"meaning {x_col} and {y_col} {relationship}."
                            )
                    else:
                        st.info("ℹ️ Not enough numeric pairs to compare.")

                # ------------------------------------------
                # SECTION 6: NUMERIC METRICS BY SEGMENT
                # ------------------------------------------
                low_card_cats = [c for c in categorical_cols_detected if 1 < active_eda_df[c].nunique(dropna=True) <= 15]

                if low_card_cats and numerical_cols:
                    st.markdown("### 🧩 Numeric Metrics by Segment")
                    st.caption("How key metrics differ across categories")

                    segment_col = low_card_cats[0]
                    for metric_col in numerical_cols[:3]:
                        agg_df = active_eda_df.groupby(segment_col)[metric_col].mean().reset_index().sort_values(by=metric_col, ascending=False)
                        st.plotly_chart(
                            px.bar(agg_df, x=segment_col, y=metric_col, text_auto=".2s",
                                   title=f"Average {metric_col} by {segment_col}"),
                            use_container_width=True
                        )
                        breakdown = ", ".join(f"{r[segment_col]}: {r[metric_col]:.2f}" for _, r in agg_df.iterrows())
                        highest = agg_df.iloc[0]
                        lowest = agg_df.iloc[-1]
                        log_chart(
                            f"Chart \"Average {metric_col} by {segment_col}\" (bar chart): {breakdown}. "
                            f"Highest is {highest[segment_col]} at {highest[metric_col]:.2f}, "
                            f"lowest is {lowest[segment_col]} at {lowest[metric_col]:.2f}."
                        )

                
                # ==================================================
                # STAGE 8: ANALYST BRIEFING + CHAT
                # One click builds the full insights report the way a

                # data analyst would after studying the whole dataset —
                # then the conversation continues as Q&A.
                # ==================================================
                st.markdown("---")
                st.markdown("## 💬 Ask InsightGenAI")
                st.write("Get insights, root causes, and recommendations.")

                if "chat_history" not in st.session_state:
                    st.session_state["chat_history"] = []

                def build_statistical_findings(data_df, num_cols, cat_cols):
                    findings_log = []
                    if num_cols:
                        for col in num_cols:
                            findings_log.append(f"Numeric Feature -> {col}:")
                            findings_log.append(f"  - Minimum value recorded: {data_df[col].min()}")
                            findings_log.append(f"  - Maximum value recorded: {data_df[col].max()}")
                            findings_log.append(f"  - Overall arithmetic average: {data_df[col].mean():.2f}")
                            findings_log.append(f"  - Median: {data_df[col].median():.2f}")
                            findings_log.append(f"  - Tail distribution score (skewness): {data_df[col].skew():.2f}")
                            findings_log.append("")
                    if cat_cols:
                        findings_log.append("Categorical Feature Sets Summary:")
                        for col in cat_cols:
                            top_val = data_df[col].mode()[0] if not data_df[col].mode().empty else "N/A"
                            unique_count = data_df[col].nunique()
                            findings_log.append(f"  - {col}: Unique variations = {unique_count}, Most Frequent Item value = '{top_val}'")
                            findings_log.append("")
                    return "\n".join(findings_log)

                if not st.session_state["chat_history"]:
                    if st.button("🧠 Generate My Analyst Briefing"):
                        api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
                        if not api_key:
                            st.error("🔑 **Gemini API Key missing.** Please set it in your environment or dashboard secrets manager.")
                        else:
                            with st.spinner("Studying your dataset like an analyst would..."):
                                try:
                                    client = genai.Client(api_key=api_key)

                                    statistical_findings = build_statistical_findings(active_eda_df, numerical_cols, categorical_cols_detected)
                                    st.session_state["computed_graph_findings"] = statistical_findings

                                    analyst_prompt = f"""You are a Senior Data Analyst presenting your findings to a CEO/Manager after fully studying a dataset.

STRICT RULES:
* Use ONLY the information present in the dataset findings below.
* Do NOT invent trends, correlations, causes, or business facts that are not supported by the data.
* Do NOT repeat every statistic — focus only on meaningful observations.
* Ignore insignificant findings.
* Do NOT suggest collecting more data or performing additional studies.
* Provide only insights that can be reasonably derived from the supplied findings.

For each finding use this exact structure:

### Insight
State the important observation discovered from the data.

### Root Cause
Explain the most likely reason based ONLY on the provided data.

### Recommendation
Provide a practical action directly related to the finding.

Requirements:
* Return the top 5-8 most important insights.
* Keep each section concise and in plain English.
* Avoid generic recommendations.
* Prioritize findings with the highest potential business impact.

Dataset Findings:

{statistical_findings}

Charts Generated (titles and what each shows):
{chr(10).join(f"- {c}" for c in st.session_state.get("chart_log", [])) or "None"}

Automated Data Alerts (quality/trend flags already detected by the system):
{chr(10).join(f"- {a}" for a in st.session_state.get("auto_alerts", [])) or "None"}
"""
                                    response = client.models.generate_content(
                                        model='gemini-2.5-flash',
                                        contents=analyst_prompt,
                                    )

                                    st.session_state["ai_report_markdown"] = response.text
                                    st.session_state["chat_history"].append({"role": "assistant", "content": response.text})
                                    st.rerun()

                                except Exception as llm_error:
                                    st.error(f"❌ LLM Processing Engine Failed: {llm_error}")

                for msg in st.session_state["chat_history"]:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

                if "ai_report_markdown" in st.session_state:
                    pdf_file_path = create_pdf(st.session_state["ai_report_markdown"])
                    with open(pdf_file_path, "rb") as pdf_file:
                        st.download_button(
                            label="📥 Download Briefing as PDF",
                            data=pdf_file,
                            file_name="InsightGenAI_Analyst_Report.pdf",
                            mime="application/pdf"
                        )

                if st.session_state["chat_history"]:
                    user_question = st.chat_input("Ask anything about your data...")

                    if user_question:
                        st.session_state["chat_history"].append({"role": "user", "content": user_question})
                        with st.chat_message("user"):
                            st.markdown(user_question)

                        api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
                        if not api_key:
                            st.error("🔑 Gemini API Key missing.")
                        else:
                            with st.spinner("Analyzing your data to answer..."):
                                try:
                                    client = genai.Client(api_key=api_key)

                                    chat_context_df = st.session_state["cleaned_dataset_df"]
                                    sample_preview = chat_context_df.head(10).to_string()
                                    stats_summary = chat_context_df.describe(include='all').astype(str).fillna("-").to_string()

                                    chart_log_text = "\n".join(
                                        f"- {c}" for c in st.session_state.get("chart_log", [])
                                    ) or "No charts logged yet."

                                    # Full prior turns (everything except the question just asked,
                                    # which is appended separately below) so the model has real
                                    # conversation memory, like a normal chatbot.
                                    prior_turns = st.session_state["chat_history"][:-1]
                                    conversation_text = "\n\n".join(
                                        f"{'User' if m['role'] == 'user' else 'Analyst'}: {m['content']}"
                                        for m in prior_turns
                                    ) or "(no prior messages)"

                                    chat_prompt = f"""You are a Senior Data Analyst having an ongoing chat conversation with a CEO/Manager about their dataset. Behave like a normal, helpful chatbot — remember what was already discussed and respond naturally to whatever is asked, including questions about specific charts on screen.

CHARTS CURRENTLY ON SCREEN (exact titles and what each one shows, with real numbers):
{chart_log_text}

AUTOMATED DATA ALERTS (quality/trend flags already detected by the system):
{chr(10).join(f"- {a}" for a in st.session_state.get("auto_alerts", [])) or "None"}

STATISTICAL PROFILE:
{st.session_state.get("computed_graph_findings", "Not available")}

BRIEFING ALREADY SHARED:
{st.session_state.get("ai_report_markdown", "Not available")}

DATA SAMPLE (first 10 rows):
{sample_preview}

DESCRIPTIVE STATISTICS:
{stats_summary}

CONVERSATION SO FAR:
{conversation_text}

RULES:
- If the question refers to "this chart", "that graph", or similar, match it to the most relevant entry in CHARTS CURRENTLY ON SCREEN and explain it using its actual numbers. If more than one chart could match, briefly cover the most likely one(s).
- Ground every data claim in the context above — never invent numbers, categories, or trends not present in it.
- For general or clarifying questions that aren't about specific data facts, just respond naturally and helpfully, like a normal chat assistant would.
- Remember and build on the conversation so far — don't repeat the full briefing unless asked.
- Answer in plain, simple English — no jargon, no code, no technical column-type talk.
- Explain the "why" behind data-related answers, referencing specific numbers where relevant.
- Keep answers concise: a direct answer first, then brief reasoning, then a recommendation if relevant.

New Question: {user_question}
"""
                                    chat_response = client.models.generate_content(
                                        model='gemini-2.5-flash',
                                        contents=chat_prompt,
                                    )

                                    answer_text = chat_response.text
                                    st.session_state["chat_history"].append({"role": "assistant", "content": answer_text})
                                    with st.chat_message("assistant"):
                                        st.markdown(answer_text)

                                except Exception as chat_error:
                                    st.error(f"❌ Chatbot Engine Failed: {chat_error}")

    except Exception as e:
        st.error(f"❌ Error processing dataset: {e}")

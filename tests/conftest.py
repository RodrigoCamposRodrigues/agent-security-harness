import os

# cli.main() loads .env, and load_dotenv never overrides a variable that is already set.
# Setting these first keeps the test suite from sending traces to LangSmith.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

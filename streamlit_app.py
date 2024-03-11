import streamlit as st
from gitlab_sprint_helper import GitLabSprintHelper
from datetime import datetime


# Function to fetch MR rate data
def fetch_data():
    with st.spinner("Fetching data..."):
        helper = GitLabSprintHelper(
            st.secrets["gitlab"]["private_token"], st.secrets["gitlab"]["group_id"]
        )
        data = helper.get_mr_rate_for_all_sprints()
    return data


# Layout
st.title("MR Rate Over Time")

# Fetch data
data = fetch_data()

# Extract and plot data
dates = [sprint["start_date"] for sprint in data]
mr_rates = [sprint["mr_rate"] for sprint in data]

# Plotting the MR rate over time
st.line_chart({date: rate for date, rate in zip(dates, mr_rates)})

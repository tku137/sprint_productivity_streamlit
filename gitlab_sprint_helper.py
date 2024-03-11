import gitlab
import re
from datetime import datetime


class GitLabSprintHelper:
    def __init__(self, private_token, group_id):
        self.gl = gitlab.Gitlab(private_token=private_token)
        self.group_id = group_id
        self.group = self.gl.groups.get(group_id, lazy=True)

    def find_sprint_epic_by_name(self, sprint_name: str):  # type: ignore
        epics = self.group.epics.list(all=True)
        for epic in epics:
            if epic.title.startswith("Sprint") and sprint_name in epic.title:
                return epic

    def list_all_sprints(self):
        sprints = self.group.epics.list(all=True)
        sprint_pattern = re.compile(r"Sprint \d+/\d+: .+")
        filtered_sprints = [
            sprint for sprint in sprints if sprint_pattern.match(sprint.title)
        ]
        return filtered_sprints

    def fetch_epic_comments(self, epic):
        return epic.notes.list(all=True)

    def split_sprint_comments(self, comments):
        sorted_comments = sorted(
            comments,
            key=lambda x: datetime.strptime(x.created_at, "%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        goal_pattern = re.compile(r"^\s*#+\s*.*goal", re.IGNORECASE)
        review_splitter_pattern = re.compile(r"^\s*#\s*Review\s*$", re.IGNORECASE)
        reflection_pattern = re.compile(r"^\s*#+\s*.*reflection", re.IGNORECASE)

        planning_comments, review_comments = [], []
        review_section_started = False

        for comment in sorted_comments:
            if review_splitter_pattern.match(comment.body.strip()):
                review_section_started = True
                continue

            if review_section_started and reflection_pattern.match(comment.body):
                review_comments.append(comment)
            elif goal_pattern.match(comment.body):
                planning_comments.append(comment)

        return planning_comments, review_comments

    def fetch_created_mrs_in_sprint(self, sprint) -> list:
        mrs = list(
            self.group.mergerequests.list(
                all=True,
                created_after=sprint.start_date,
                created_before=sprint.end_date,
            )
        )
        return mrs

    def fetch_active_mrs_in_sprint(self, sprint) -> list:
        mrs = list(
            self.group.mergerequests.list(
                all=True,
                updated_after=sprint.start_date,
                updated_before=sprint.end_date,
            )
        )
        return mrs

    def fetch_mr_comments(self, merge_request):
        project = self.gl.projects.get(merge_request.project_id)
        mr = project.mergerequests.get(merge_request.iid)
        comments = []

        for discussion in mr.discussions.list(all=True):
            for note in discussion.attributes["notes"]:
                if not note["system"]:
                    comments.append(note)

        return comments

    def calculate_mr_rate(self, planning_comments, mrs_in_sprint):
        team_members = {comment.author["username"] for comment in planning_comments}
        mr_rate = len(mrs_in_sprint) / len(team_members) if team_members else 0
        return mr_rate

    def calculate_mr_completion_rate(self, mrs_in_sprint):
        merged_mrs = [mr for mr in mrs_in_sprint if mr.state == "merged"]
        if not mrs_in_sprint:
            return 0
        return len(merged_mrs) / len(mrs_in_sprint)

    def calculate_average_time_to_merge(self, mrs_in_sprint):
        total_time_to_merge = 0
        merged_mrs = [mr for mr in mrs_in_sprint if mr.state == "merged"]
        for mr in merged_mrs:
            created_at = datetime.strptime(mr.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
            merged_at = datetime.strptime(mr.merged_at, "%Y-%m-%dT%H:%M:%S.%fZ")
            total_time_to_merge += (merged_at - created_at).total_seconds()

        if not merged_mrs:
            return 0
        return total_time_to_merge / len(merged_mrs) / 3600  # return in hours

    def calculate_code_review_efficiency(self, mrs_in_sprint):
        total_discussions = 0
        mr_with_discussions = 0
        for mr in mrs_in_sprint:
            comments = self.fetch_mr_comments(mr)
            if comments:
                total_discussions += len(comments)
                mr_with_discussions += 1

        if not mrs_in_sprint:
            return 0, 0
        average_discussions_per_mr = total_discussions / len(mrs_in_sprint)
        percentage_without_discussions = (
            (len(mrs_in_sprint) - mr_with_discussions) / len(mrs_in_sprint)
        ) * 100
        return average_discussions_per_mr, percentage_without_discussions

    def _extract_issue_info_from_comments(self, comments):
        """Extract project paths and issue IDs from comments."""
        issue_info = []
        issue_url_pattern = re.compile(
            r"https://gitlab.com/([\w-]+/[\w-]+/[\w-]+/-/(issues|work_items)/(\d+))"
        )

        for comment in comments:
            matches = issue_url_pattern.findall(comment.body)
            for full_match, _, issue_id in matches:
                project_path = "/".join(full_match.split("/")[:-3])
                issue_info.append((project_path, issue_id))

        return issue_info

    def calculate_planned_issue_completion_rate(self, planning_comments):
        issue_infos = self._extract_issue_info_from_comments(planning_comments)
        completed_issues = 0

        for project_path, issue_id in issue_infos:
            # Adjust this part to fetch the project and issue using the GitLab API
            project = self.gl.projects.get(project_path)
            issue = project.issues.get(issue_id)
            if issue.state in ["closed", "merged"]:
                completed_issues += 1

        if not issue_infos:
            return 0  # Avoid division by zero if no issues were found
        return completed_issues / len(issue_infos)

    def calculate_scope_change_rate(self, planning_comments, review_comments):
        initial_planned_issue_info = set(
            self._extract_issue_info_from_comments(planning_comments)
        )
        all_mentioned_issue_info = set(
            self._extract_issue_info_from_comments(review_comments + planning_comments)
        )

        new_issues = all_mentioned_issue_info - initial_planned_issue_info
        if not initial_planned_issue_info:
            # Avoid division by zero and return 0 for both values if no initial issues
            return 0, 0

        scope_change_rate = len(new_issues) / len(initial_planned_issue_info)
        return len(new_issues), scope_change_rate

    def calculate_mr_collaboration_score(self, mrs_in_sprint):
        unique_contributors = set()
        total_participants = 0
        total_discussions = 0

        for mr in mrs_in_sprint:
            comments = self.fetch_mr_comments(mr)
            for comment in comments:
                unique_contributors.add(comment["author"]["id"])
                total_participants += 1
            if comments:
                total_discussions += 1

        # Avoid division by zero
        average_participants_per_discussion = (
            (total_participants / total_discussions) if total_discussions else 0
        )

        return len(unique_contributors), average_participants_per_discussion

    def calculate_work_distribution(self, mrs_in_sprint):
        contribution_counts = {}

        for mr in mrs_in_sprint:
            author_username = mr.author["username"]
            if author_username in contribution_counts:
                contribution_counts[author_username] += 1
            else:
                contribution_counts[author_username] = 1

        return contribution_counts

    def calculate_sprint_metrics(self, sprint):
        comments = self.fetch_epic_comments(sprint)
        planning_comments, review_comments = self.split_sprint_comments(comments)
        new_mrs = self.fetch_created_mrs_in_sprint(sprint)
        active_mrs = self.fetch_active_mrs_in_sprint(sprint)

        average_discussions, percent_without_discussions = (
            self.calculate_code_review_efficiency(active_mrs)
        )
        new_issues, scope_change_rate = self.calculate_scope_change_rate(
            planning_comments, review_comments
        )
        unique_contributors, avg_participants = self.calculate_mr_collaboration_score(
            active_mrs
        )

        metrics = {
            # summary
            "sprint_name": sprint.title,
            "start_date": sprint.start_date,
            "end_date": sprint.end_date,
            "total_planning_comments": len(planning_comments),
            "total_review_comments": len(review_comments),
            "new_mrs_in_sprint": len(new_mrs),
            "all_active_mrs_in_sprint": len(active_mrs),
            # metrics
            "mr_rate": self.calculate_mr_rate(planning_comments, new_mrs),
            "mr_completion_rate": self.calculate_mr_completion_rate(new_mrs),
            "average_time_to_merge": self.calculate_average_time_to_merge(active_mrs),
            "average_discussions_per_mr": average_discussions,
            "percent_mrs_dwithout_iscussions": percent_without_discussions,
            "planned_issue_completion_rate": self.calculate_planned_issue_completion_rate(
                planning_comments
            ),
            "scope_change_new_issues": new_issues,
            "scope_change_rate": scope_change_rate,
            # collaboration and work distribution
            "collaboration_score_unique_contributors": unique_contributors,
            "collaboration_score_avg_participants": avg_participants,
            # work distribution
            "work_distribution": self.calculate_work_distribution(active_mrs),
        }

        return metrics

    def get_metrics_for_all_sprints(self):
        all_sprint_metrics = []
        sprints = self.list_all_sprints()
        for sprint in sprints:
            print(f"Calculating metrics for {sprint.title}")
            metrics = self.calculate_sprint_metrics(sprint)
            all_sprint_metrics.append(metrics)

        return all_sprint_metrics

    def get_mr_rate_for_all_sprints(self):
        all_sprint_mr_rates = []
        sprints = self.list_all_sprints()
        for sprint in sprints:
            print(f"Calculating metrics for {sprint.title}")
            comments = self.fetch_epic_comments(sprint)
            planning_comments, _ = self.split_sprint_comments(comments)
            new_mrs = self.fetch_created_mrs_in_sprint(sprint)
            mr_rate = self.calculate_mr_rate(planning_comments, new_mrs)
            all_sprint_mr_rates.append(
                {
                    "sprint_name": sprint.title,
                    "start_date": sprint.start_date,
                    "end_date": sprint.end_date,
                    "mr_rate": mr_rate,
                }
            )

        return all_sprint_mr_rates

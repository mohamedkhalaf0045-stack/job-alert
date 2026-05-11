class CloudStatus {
  final String lampColor; // green | yellow | red | grey
  final String lastRunTime;
  final int jobCount;
  final bool scheduleActive;
  final int runId;
  final int workflowId;
  final String htmlUrl;
  final String conclusion;

  const CloudStatus({
    this.lampColor = 'grey',
    this.lastRunTime = 'Unknown',
    this.jobCount = 0,
    this.scheduleActive = true,
    this.runId = 0,
    this.workflowId = 0,
    this.htmlUrl = '',
    this.conclusion = '',
  });
}

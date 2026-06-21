class Config {
  static const githubToken = String.fromEnvironment('GITHUB_TOKEN', defaultValue: '');
  static const githubRepo  = 'mohamedkhalaf0045-stack/job-alert';
  static const webAppUrl = String.fromEnvironment(
    'WEB_APP_URL',
    defaultValue: 'https://job-alert-git-main-mohamedkhalaf0045-stacks-projects.vercel.app',
  );
  static const supabaseUrl = 'https://xsuqhjmonzcguedekqjt.supabase.co';
  static const supabaseKey =
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
      '.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzdXFoam1vbnpjZ3VlZGVrcWp0Iiwi'
      'cm9sZSI6ImFub24iLCJpYXQiOjE3NzgzNDA1ODAsImV4cCI6MjA5MzkxNjU4MH0'
      '.vlDyF47Yv-KocPHeedwbNnEtdnE6m1W1fHOM33ITVz0';
}

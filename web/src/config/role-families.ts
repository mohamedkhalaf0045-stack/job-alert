export interface RoleFamily {
  label: string
  keywords: string[]
}

export const ROLE_FAMILIES: Record<string, RoleFamily> = {
  it_support: {
    label: 'IT Support / Help Desk',
    keywords: ['IT Support', 'Help Desk', 'Service Desk', 'Desktop Support', 'Technical Support Engineer'],
  },
  sysadmin: {
    label: 'System Administrator',
    keywords: ['System Administrator', 'Windows Administrator', 'IT Administrator', 'Infrastructure Engineer'],
  },
  network: {
    label: 'Network Engineer',
    keywords: ['Network Engineer', 'Network Administrator', 'NOC Engineer', 'Network Support Technician'],
  },
  devops: {
    label: 'DevOps / Cloud',
    keywords: ['DevOps Engineer', 'Cloud Engineer', 'Azure Administrator', 'AWS Engineer', 'Site Reliability Engineer'],
  },
  security: {
    label: 'Cybersecurity',
    keywords: ['Security Analyst', 'SOC Analyst', 'Information Security Analyst', 'Cybersecurity Engineer'],
  },
  developer: {
    label: 'Software Developer',
    keywords: ['Software Developer', 'Software Engineer', 'Full Stack Developer', 'Frontend Developer', 'Backend Developer'],
  },
  data: {
    label: 'Data / Analytics',
    keywords: ['Data Analyst', 'Data Engineer', 'Business Intelligence Analyst', 'Data Scientist'],
  },
  database: {
    label: 'Database Administrator',
    keywords: ['Database Administrator', 'DBA', 'SQL Developer', 'Database Engineer'],
  },
}

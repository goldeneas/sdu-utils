export interface Basics {
  name: string;
  title: string;
  location: string;
  email: string;
  linkedin?: string;
  github?: string;
  website?: string;
  summary: string;
}

export interface Experience {
  role: string;
  company: string;
  location?: string;
  start: string;
  end: string;
  bullets: string[];
}

export interface Project {
  name: string;
  link?: string;
  start?: string;
  end?: string;
  tagline?: string;
  bullets: string[];
}

export interface Education {
  degree: string;
  institution: string;
  location?: string;
  start: string;
  end: string;
  bullets: string[];
}

export interface SkillGroup {
  group: string;
  items: string[];
}

export interface LanguageSkill {
  name: string;
  level: string;
}

export interface CV {
  basics: Basics;
  experience: Experience[];
  projects: Project[];
  education: Education[];
  coursework?: string[];
  skills: SkillGroup[];
  languages: LanguageSkill[];
}

import type { SoftwareRoleCategory } from '../types';

/**
 * Configuration for role classification
 */
export interface RoleClassificationConfig {
  /** Keywords by category */
  categoryKeywords: Record<SoftwareRoleCategory, string[]>;

  /** Department name patterns */
  techDepartments: RegExp[];

  /** Title exclusion patterns (non-tech roles) */
  exclusionPatterns: RegExp[];
}

/**
 * Role classification configuration
 */
export const ROLE_CLASSIFICATION_CONFIG: RoleClassificationConfig = {
  categoryKeywords: {
    frontend: [
      'frontend',
      'front-end',
      'front end',
      'react',
      'vue',
      'angular',
      'ui engineer',
      'web developer',
      'javascript developer',
      'typescript developer',
      'css',
      'html',
    ],
    backend: [
      'backend',
      'back-end',
      'back end',
      'server',
      'api',
      'microservices',
      'java',
      'python',
      'go',
      'rust',
      'node',
      'database',
      'sql',
    ],
    fullstack: [
      'fullstack',
      'full-stack',
      'full stack',
      'software engineer',
      'software developer',
      'application developer',
    ],
    mobile: [
      'mobile',
      'ios',
      'android',
      'react native',
      'flutter',
      'swift',
      'kotlin',
      'mobile developer',
    ],
    data: [
      'data engineer',
      'data scientist',
      'data analyst',
      'analytics',
      'etl',
      'data pipeline',
      'big data',
      'hadoop',
      'spark',
    ],
    ml: [
      'machine learning',
      'ml engineer',
      'ai engineer',
      'artificial intelligence',
      'deep learning',
      'nlp',
      'computer vision',
      'tensorflow',
      'pytorch',
    ],
    devops: [
      'devops',
      'site reliability',
      'sre',
      'infrastructure',
      'ci/cd',
      'kubernetes',
      'docker',
      'terraform',
      'cloud',
      'aws',
      'azure',
      'gcp',
    ],
    platform: [
      'platform engineer',
      'systems engineer',
      'infrastructure engineer',
      'cloud engineer',
      'distributed systems',
    ],
    qa: [
      'qa',
      'quality assurance',
      'test engineer',
      'sdet',
      'automation',
      'testing',
      'quality engineer',
    ],
    security: [
      'security',
      'cybersecurity',
      'infosec',
      'appsec',
      'penetration test',
      'security engineer',
    ],
    graphics: [
      'graphics',
      'rendering',
      'webgl',
      'opengl',
      'vulkan',
      'shader',
      'game',
      'visualization',
    ],
    embedded: ['embedded', 'firmware', 'hardware', 'iot', 'rtos', 'c++', 'microcontroller'],
    otherTech: [
      'engineer',
      'developer',
      'programmer',
      'technical',
      'software',
      'architect',
      'engineering',
    ],
    nonTech: [],
  },

  techDepartments: [
    /engineering/i,
    /software/i,
    /technology/i,
    /technical/i,
    /product/i,
    /r&d/i,
    /research/i,
    /development/i,
    /it/i,
    /information technology/i,
  ],

  exclusionPatterns: [
    /\bhuman resources?\b/i,
    /\bhr\b/i,
    /\brecruiter\b/i,
    /\btalent acquisition\b/i,
    /\bsales\b/i,
    /\bmarketing\b/i,
    /\baccounting\b/i,
    /\bfinance\b/i,
    /\blegal\b/i,
    /\bcompliance\b/i,
    /\bfacilities\b/i,
    /\badministrative\b/i,
    /\boffice manager\b/i,
    /\bcustomer success\b/i,
    /\bcustomer support\b/i,
    /\bsupport specialist\b/i,
  ],
};

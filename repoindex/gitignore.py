"""
.gitignore generation based on detected languages and project structure.
"""

from typing import Dict, List, Optional
import os


def generate_gitignore_content(languages: Dict[str, Dict[str, int]], repo_path: Optional[str] = None) -> str:
    """Generate .gitignore content based on detected languages.
    
    Args:
        languages: Dictionary from detect_languages() with language names and stats
        repo_path: Optional path to repository for additional detection
        
    Returns:
        Complete .gitignore content as string
    """
    sections = []
    
    # Always include common OS and editor patterns
    sections.append(_get_common_patterns())
    
    # Add language-specific patterns
    language_patterns = set()
    for language in languages.keys():
        patterns = _get_language_patterns(language)
        language_patterns.update(patterns)
    
    if language_patterns:
        sections.append(_format_section("Language-specific files", sorted(language_patterns)))
    
    # Add project structure based patterns
    if repo_path:
        structure_patterns = _detect_project_structure_patterns(repo_path)
        if structure_patterns:
            sections.append(_format_section("Project structure", sorted(structure_patterns)))
    
    return "\n\n".join(sections) + "\n"


def _get_common_patterns() -> str:
    """Get common OS and editor patterns."""
    return """# OS generated files
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
ehthumbs.db
Thumbs.db
desktop.ini

# Editor files
.vscode/
.idea/
*.swp
*.swo
*~
.vim/
.netrwhist
*.sublime-project
*.sublime-workspace

# Environment files
.env
.env.local
.env.*.local

# Logs
*.log
logs/

# Temporary files
tmp/
temp/
.tmp/"""


def _get_language_patterns(language: str) -> List[str]:
    """Get .gitignore patterns for a specific language."""
    patterns = {
        'Python': [
            '__pycache__/',
            '*.py[cod]',
            '*$py.class',
            '*.so',
            '.Python',
            'build/',
            'develop-eggs/',
            'dist/',
            'downloads/',
            'eggs/',
            '.eggs/',
            'lib/',
            'lib64/',
            'parts/',
            'sdist/',
            'var/',
            'wheels/',
            'share/python-wheels/',
            '*.egg-info/',
            '.installed.cfg',
            '*.egg',
            'MANIFEST',
            '# PyInstaller',
            '*.manifest',
            '*.spec',
            '# Installer logs',
            'pip-log.txt',
            'pip-delete-this-directory.txt',
            '# Unit test / coverage reports',
            'htmlcov/',
            '.tox/',
            '.nox/',
            '.coverage',
            '.coverage.*',
            '.cache',
            'nosetests.xml',
            'coverage.xml',
            '*.cover',
            '*.py,cover',
            '.hypothesis/',
            '.pytest_cache/',
            'cover/',
            '# Virtual environments',
            '.env',
            '.venv',
            'env/',
            'venv/',
            'ENV/',
            'env.bak/',
            'venv.bak/',
            '# Jupyter Notebook',
            '.ipynb_checkpoints',
            '# IPython',
            'profile_default/',
            'ipython_config.py',
            '# pyenv',
            '.python-version',
            '# Celery',
            'celerybeat-schedule',
            'celerybeat.pid',
            '# SageMath parsed files',
            '*.sage.py',
            '# Spyder project settings',
            '.spyderproject',
            '.spyproject',
            '# Rope project settings',
            '.ropeproject',
            '# mkdocs documentation',
            '/site',
            '# mypy',
            '.mypy_cache/',
            '.dmypy.json',
            'dmypy.json',
            '# Pyre type checker',
            '.pyre/',
            '# pytype static type analyzer',
            '.pytype/',
        ],
        
        'JavaScript': [
            'node_modules/',
            'npm-debug.log*',
            'yarn-debug.log*',
            'yarn-error.log*',
            'lerna-debug.log*',
            '.pnpm-debug.log*',
            '# Diagnostic reports',
            'report.[0-9]*.[0-9]*.[0-9]*.[0-9]*.json',
            '# Runtime data',
            'pids',
            '*.pid',
            '*.seed',
            '*.pid.lock',
            '# Coverage directory used by tools like istanbul',
            'coverage/',
            '*.lcov',
            '# nyc test coverage',
            '.nyc_output',
            '# Grunt intermediate storage',
            '.grunt',
            '# Bower dependency directory',
            'bower_components',
            '# node-waf configuration',
            '.lock-wscript',
            '# Compiled binary addons',
            'build/Release',
            '# Dependency directories',
            'jspm_packages/',
            '# TypeScript cache',
            '*.tsbuildinfo',
            '# Optional npm cache directory',
            '.npm',
            '# Optional eslint cache',
            '.eslintcache',
            '# Microbundle cache',
            '.rpt2_cache/',
            '.rts2_cache_cjs/',
            '.rts2_cache_es/',
            '.rts2_cache_umd/',
            '# Optional REPL history',
            '.node_repl_history',
            '# Output of \'npm pack\'',
            '*.tgz',
            '# Yarn Integrity file',
            '.yarn-integrity',
            '# parcel-bundler cache',
            '.cache',
            '.parcel-cache',
            '# Next.js build output',
            '.next',
            'out',
            '# Nuxt.js build / generate output',
            '.nuxt',
            'dist',
            '# Gatsby files',
            '.cache/',
            'public',
            '# Storybook build outputs',
            '.out',
            '.storybook-out',
            '# Temporary folders',
            '.tmp',
        ],
        
        'TypeScript': [
            '*.tsbuildinfo',
            '# TypeScript cache',
            '*.tsbuildinfo',
            '# Compiled TypeScript output',
            '*.js',
            '*.js.map',
            '*.d.ts',
        ],
        
        'Java': [
            '*.class',
            '# Log file',
            '*.log',
            '# BlueJ files',
            '*.ctxt',
            '# Mobile Tools for Java (J2ME)',
            '.mtj.tmp/',
            '# Package Files',
            '*.jar',
            '*.war',
            '*.nar',
            '*.ear',
            '*.zip',
            '*.tar.gz',
            '*.rar',
            '# virtual machine crash logs',
            'hs_err_pid*',
            '# Maven',
            'target/',
            'pom.xml.tag',
            'pom.xml.releaseBackup',
            'pom.xml.versionsBackup',
            'pom.xml.next',
            'release.properties',
            'dependency-reduced-pom.xml',
            'buildNumber.properties',
            '.mvn/timing.properties',
            '.mvn/wrapper/maven-wrapper.properties',
            '# Gradle',
            '.gradle',
            'build/',
            '!gradle/wrapper/gradle-wrapper.jar',
            '!**/src/main/**/build/',
            '!**/src/test/**/build/',
            '# IntelliJ IDEA',
            '.idea',
            '*.iws',
            '*.iml',
            '*.ipr',
            'out/',
            '!**/src/main/**/out/',
            '!**/src/test/**/out/',
            '# Eclipse',
            '.apt_generated',
            '.classpath',
            '.factorypath',
            '.project',
            '.settings',
            '.springBeans',
            '.sts4-cache',
        ],
        
        'Go': [
            '# Binaries for programs and plugins',
            '*.exe',
            '*.exe~',
            '*.dll',
            '*.so',
            '*.dylib',
            '# Test binary, built with `go test -c`',
            '*.test',
            '# Output of the go coverage tool',
            '*.out',
            '# Dependency directories',
            'vendor/',
            '# Go workspace file',
            'go.work',
        ],
        
        'Rust': [
            '# Generated by Cargo',
            '/target/',
            '# Remove Cargo.lock from gitignore if creating an executable',
            'Cargo.lock',
            '# These are backup files generated by rustfmt',
            '**/*.rs.bk',
            '# MSVC Windows builds of rustc generate these, which store debugging information',
            '*.pdb',
        ],
        
        'C': [
            '# Prerequisites',
            '*.d',
            '# Object files',
            '*.o',
            '*.ko',
            '*.obj',
            '*.elf',
            '# Linker output',
            '*.ilk',
            '*.map',
            '*.exp',
            '# Precompiled Headers',
            '*.gch',
            '*.pch',
            '# Libraries',
            '*.lib',
            '*.a',
            '*.la',
            '*.lo',
            '# Shared objects',
            '*.dll',
            '*.so',
            '*.so.*',
            '*.dylib',
            '# Executables',
            '*.exe',
            '*.out',
            '*.app',
            '*.i*86',
            '*.x86_64',
            '*.hex',
            '# Debug files',
            '*.dSYM/',
            '*.su',
            '*.idb',
            '*.pdb',
            '# Kernel Module Compile Results',
            '*.mod*',
            '*.cmd',
            '.tmp_versions/',
            'modules.order',
            'Module.symvers',
            'Mkfile.old',
            'dkms.conf',
        ],
        
        'C++': [
            '# Prerequisites',
            '*.d',
            '# Compiled Object files',
            '*.slo',
            '*.lo',
            '*.o',
            '*.obj',
            '# Precompiled Headers',
            '*.gch',
            '*.pch',
            '# Compiled Dynamic libraries',
            '*.so',
            '*.dylib',
            '*.dll',
            '# Fortran module files',
            '*.mod',
            '*.smod',
            '# Compiled Static libraries',
            '*.lai',
            '*.la',
            '*.a',
            '*.lib',
            '# Executables',
            '*.exe',
            '*.out',
            '*.app',
        ],
        
        'C#': [
            '# Build results',
            '[Dd]ebug/',
            '[Dd]ebugPublic/',
            '[Rr]elease/',
            '[Rr]eleases/',
            'x64/',
            'x86/',
            '[Ww][Ii][Nn]32/',
            '[Aa][Rr][Mm]/',
            '[Aa][Rr][Mm]64/',
            'bld/',
            '[Bb]in/',
            '[Oo]bj/',
            '[Ll]og/',
            '[Ll]ogs/',
            '# Visual Studio cache files',
            '*.suo',
            '*.user',
            '*.userosscache',
            '*.sln.docstates',
            '# User-specific files (MonoDevelop/Xamarin Studio)',
            '*.userprefs',
            '# Mono auto generated files',
            'mono_crash.*',
            '# Build results',
            '[Dd]ebug/',
            '[Dd]ebugPublic/',
            '[Rr]elease/',
            '[Rr]eleases/',
            'x64/',
            'x86/',
            'bld/',
            '[Bb]in/',
            '[Oo]bj/',
            '[Ll]og/',
            '# Files built by Visual Studio',
            '*_i.c',
            '*_p.c',
            '*_h.h',
            '*.ilk',
            '*.meta',
            '*.obj',
            '*.iobj',
            '*.pch',
            '*.pdb',
            '*.ipdb',
            '*.pgc',
            '*.pgd',
            '*.rsp',
            '*.sbr',
            '*.tlb',
            '*.tli',
            '*.tlh',
            '*.tmp',
            '*.tmp_proj',
            '*_wpftmp.csproj',
            '*.log',
            '*.vspscc',
            '*.vssscc',
            '.builds',
            '*.pidb',
            '*.svclog',
            '*.scc',
        ],
        
        'Swift': [
            '# Xcode',
            '#',
            '# gitignore contributors: remember to update Global/Xcode.gitignore, Objective-C.gitignore & Swift.gitignore',
            '## User settings',
            'xcuserdata/',
            '## compatibility with Xcode 8 and earlier (ignoring not required starting Xcode 9)',
            '*.xcscmblueprint',
            '*.xccheckout',
            '## compatibility with Xcode 3 and earlier (ignoring not required starting Xcode 4)',
            'build/',
            'DerivedData/',
            '*.moved-aside',
            '*.pbxuser',
            '!default.pbxuser',
            '*.mode1v3',
            '!default.mode1v3',
            '*.mode2v3',
            '!default.mode2v3',
            '*.perspectivev3',
            '!default.perspectivev3',
            '## Obj-C/Swift specific',
            '*.hmap',
            '## App packaging',
            '*.ipa',
            '*.dSYM.zip',
            '*.dSYM',
            '## Playgrounds',
            'timeline.xctimeline',
            'playground.xcworkspace',
            '# Swift Package Manager',
            'Packages/',
            'Package.pins',
            'Package.resolved',
            '*.xcodeproj',
            '# Xcode automatically generates this directory with a .xcworkspacedata file and xcuserdata',
            '*.xcworkspace',
            '# CocoaPods',
            'Pods/',
            '# Carthage',
            'Carthage/Build/',
            '# Accio dependency management',
            'Dependencies/',
            '.accio/',
            '# fastlane',
            'fastlane/report.xml',
            'fastlane/Preview.html',
            'fastlane/screenshots/**/*.png',
            'fastlane/test_output',
        ],
        
        'Ruby': [
            '*.gem',
            '*.rbc',
            '/.config',
            '/coverage/',
            '/InstalledFiles',
            '/pkg/',
            '/spec/reports/',
            '/spec/examples.txt',
            '/test/tmp/',
            '/test/version_tmp/',
            '/tmp/',
            '# Used by dotenv library to load environment variables.',
            '.env',
            '# Ignore Byebug command history file.',
            '.byebug_history',
            '## Specific to RubyMotion:',
            '.dat*',
            '.repl_history',
            'build/',
            '*.bridgesupport',
            'build-iPhoneOS/',
            'build-iPhoneSimulator/',
            '## Specific to RubyMotion (use of CocoaPods):',
            'Pods/',
            'vendor/bundle/',
            '.bundle/',
            '## Documentation cache and generated files:',
            '/.yardoc/',
            '/_yardoc/',
            '/doc/',
            '/rdoc/',
            '## Environment normalization:',
            '/.bundle/',
            '/vendor/bundle',
            '/lib/bundler/man/',
            '# for a library or gem, you might want to ignore these files since the code is',
            '# intended to run in multiple environments; otherwise, check them in:',
            'Gemfile.lock',
            '.ruby-version',
            '.ruby-gemset',
            '# unless supporting rvm < 1.11.0 or doing something fancy, ignore this:',
            '.rvmrc',
        ],
        
        'PHP': [
            '# Log files',
            '*.log',
            '# Runtime data',
            'pids',
            '*.pid',
            '*.seed',
            '*.pid.lock',
            '# Directory for instrumented libs generated by jscoverage/JSCover',
            'lib-cov',
            '# Coverage directory used by tools like istanbul',
            'coverage',
            '# nyc test coverage',
            '.nyc_output',
            '# Grunt intermediate storage',
            '.grunt',
            '# Bower dependency directory',
            'bower_components',
            '# node-waf configuration',
            '.lock-wscript',
            '# Compiled binary addons',
            'build/Release',
            '# Dependency directories',
            'node_modules/',
            'jspm_packages/',
            '# Optional npm cache directory',
            '.npm',
            '# Optional REPL history',
            '.node_repl_history',
            '# Output of \'npm pack\'',
            '*.tgz',
            '# Yarn Integrity file',
            '.yarn-integrity',
            '# dotenv environment variables file',
            '.env',
            '.env.test',
            '# parcel-bundler cache',
            '.cache',
            '.parcel-cache',
            '# next.js build output',
            '.next',
            '# Composer',
            '/vendor/',
            'composer.phar',
            'composer.lock',
            '/vendor',
        ],
        
        'R': [
            '# History files',
            '.Rhistory',
            '.Rapp.history',
            '# Session Data files',
            '.RData',
            '# User-specific files',
            '.Ruserdata',
            '# Example code in package build process',
            '*-Ex.R',
            '# Output files from R CMD build',
            '/*.tar.gz',
            '# Output files from R CMD check',
            '/*.Rcheck/',
            '# RStudio files',
            '.Rproj.user/',
            '# produced vignettes',
            'vignettes/*.html',
            'vignettes/*.pdf',
            '# OAuth2 token, see https://github.com/hadley/httr/releases/tag/v0.3',
            '.httr-oauth',
            '# knitr and R markdown default cache directories',
            '/*_cache/',
            '/cache/',
            '# Temporary files created by R markdown',
            '*.utf8.md',
            '*.knit.md',
            '# R Environment Variables',
            '.Renviron',
        ],
        
        'Kotlin': [
            '*.class',
            '# Log file',
            '*.log',
            '# BlueJ files',
            '*.ctxt',
            '# Mobile Tools for Java (J2ME)',
            '.mtj.tmp/',
            '# Package Files',
            '*.jar',
            '*.war',
            '*.nar',
            '*.ear',
            '*.zip',
            '*.tar.gz',
            '*.rar',
            '# virtual machine crash logs',
            'hs_err_pid*',
        ],
        
        'Scala': [
            '*.class',
            '*.log',
            '# sbt specific',
            '.cache',
            '.history',
            '.lib/',
            'dist/*',
            'target/',
            'lib_managed/',
            'src_managed/',
            'project/boot/',
            'project/plugins/project/',
            '# Scala-IDE specific',
            '.scala_dependencies',
            '.worksheet',
        ],
        
        'Dart': [
            '# Files and directories created by pub',
            '.dart_tool/',
            '.packages',
            'build/',
            '# If you\'re building an application, you may want to check-in your pubspec.lock',
            'pubspec.lock',
            '# Directory created by dartdoc',
            'doc/api/',
            '# dotenv environment variables file',
            '.env*',
            '# Avoid committing generated Javascript files:',
            '*.dart.js',
            '*.info.json',
            '*.js',
            '*.js_',
            '*.js.deps',
            '*.js.map',
        ],
    }
    
    return patterns.get(language, [])


def _detect_project_structure_patterns(repo_path: str) -> List[str]:
    """Detect additional patterns based on project structure."""
    patterns = []
    
    try:
        # Check for common config files and add related patterns
        files_in_root = os.listdir(repo_path)
        
        # Docker
        if any(f in files_in_root for f in ['Dockerfile', 'docker-compose.yml', 'docker-compose.yaml']):
            patterns.extend([
                '# Docker',
                '.dockerignore',
                'docker-compose.override.yml',
            ])
        
        # Terraform
        if any(f.endswith('.tf') for f in files_in_root):
            patterns.extend([
                '# Terraform',
                '*.tfstate',
                '*.tfstate.*',
                '.terraform/',
                '.terraform.lock.hcl',
                'terraform.tfvars',
                '*.tfvars',
            ])
        
        # Makefile
        if any(f in files_in_root for f in ['Makefile', 'makefile', 'GNUmakefile']):
            patterns.extend([
                '# Make',
                '*.o',
                '*.so',
                '*.a',
            ])
        
        # Check for docs directories
        if any(d in files_in_root for d in ['docs', 'doc', 'documentation']):
            patterns.extend([
                '# Documentation builds',
                'docs/_build/',
                'docs/site/',
                'site/',
            ])
            
    except OSError:
        pass  # Directory doesn't exist or can't be read
    
    return patterns


def _format_section(title: str, patterns: List[str]) -> str:
    """Format a section of .gitignore patterns."""
    if not patterns:
        return ""
    
    lines = [f"# {title}"]
    lines.extend(patterns)
    return "\n".join(lines)
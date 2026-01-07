# Feature: Website Grader Integration

## Overview

### Purpose and Business Value
Integrate a Python-based website grader into the cold outreach enrichment system to provide comprehensive website quality assessment. This enables us to:
- Identify quality gaps in prospects' websites (poor content, weak design, performance issues)
- Create personalized, specific outreach messages based on actual weaknesses
- Prioritize outreach to companies with clear improvement opportunities
- Differentiate our pitch by showing expertise through detailed analysis

### Success Criteria
- Successfully grade websites across 3 dimensions: Performance, Content, Design
- Identify and flag specific weak areas (deviations from average performance)
- Integrate seamlessly with existing orchestrator workflow
- Can run standalone or as part of full enrichment pipeline
- Outputs actionable insights in CSV format for outreach personalization

### Dependencies
- **External APIs**: OpenAI API (GPT-4o for vision analysis)
- **Python Libraries**: Playwright (browser automation), openai, Pillow (image processing)
- **Existing Data**: PageSpeed mobile score from `pagespeed_checker.py`
- **Environment**: Python 3.8+, OpenAI API key in `.env`

## Technical Approach

### Recommended Solution

**Architecture**: Separate Python script (`scripts/website_grader.py`) that follows the same pattern as existing enrichment modules, with integration hooks for orchestrator.

**Why This Approach**:
1. **Consistency**: Matches existing pattern of modular enrichment scripts
2. **Flexibility**: Can run standalone for testing or as part of full pipeline
3. **Cost Control**: Optional execution via `--skip-grader` flag (OpenAI API calls cost money)
4. **Reuse**: Leverages already-collected PageSpeed data instead of re-fetching
5. **Maintainability**: Clear separation of concerns, easy to debug/update

**High-Level Architecture**:
```
Input CSV
    |
    v
website_grader.py
    |
    +-- Screenshot Capture (Playwright)
    |       |
    |       v
    |   Save to /screenshots/{domain}.png
    |
    +-- Content Analysis (in-browser evaluation)
    |       |
    |       v
    |   Word count, headings, sections, nav structure
    |       |
    |       v
    |   Score: 0-100 (content_score)
    |
    +-- Design Analysis (GPT-4o Vision)
    |       |
    |       v
    |   Send screenshot to OpenAI
    |       |
    |       v
    |   Score: 0-100 (design_score)
    |
    +-- Performance Score (Reuse Existing Data)
    |       |
    |       v
    |   Read pagespeed_mobile from CSV
    |
    +-- Scoring Engine
    |       |
    |       v
    |   Calculate weighted total
    |   Identify deviations
    |   Generate analysis text
    |
    v
Output: Enriched CSV with grading columns
```

### Alternatives Considered

**Alternative 1: Inline in Orchestrator**
- **Rejected**: Would bloat orchestrator, harder to test, violates single responsibility

**Alternative 2: Content Quality via GPT**
- **Rejected**: Node version does this (80% amount + 20% GPT quality)
- **Our approach**: Content amount ONLY to save API costs
- **Rationale**: Word count/structure is sufficient signal; GPT quality check is diminishing returns

**Alternative 3: Store Screenshots in Cloud (S3)**
- **Rejected for v1**: Local storage simpler, no additional costs
- **Future**: Could add S3 upload option for long-term storage

## Implementation Specification

### Data Flow

**Input Format**:
- CSV with at minimum: `Website` column
- Optionally: `pagespeed_mobile` column (if running standalone after orchestrator)
- If `pagespeed_mobile` missing: defaults to 50 for scoring purposes

**Processing Steps**:
1. Read CSV, validate columns
2. For each website:
   a. Navigate with Playwright (headless Chromium)
   b. Wait for page load (networkidle, max 30s timeout)
   c. Capture full-page screenshot → `/screenshots/{clean_domain}.png`
   d. Extract content metrics via page.evaluate():
      - Word count (body.innerText)
      - Heading counts (h1, h2, h3)
      - Section count
      - Paragraph count
      - Navigation structure (common links: features, pricing, docs, blog, contact, about)
   e. Calculate content_score (0-100) based on thresholds
   f. Send screenshot to OpenAI GPT-4o vision API
   g. Parse design_score (0-100) from JSON response
   h. Read performance score from existing `pagespeed_mobile` column (or default to 50)
   i. Calculate weighted total_grade_score
   j. Determine letter_grade (A+ to F)
   k. Analyze deviations, generate grade_analysis, weak_areas, strong_areas
3. Add all grading columns to DataFrame
4. Save enriched CSV

**Output Format**:
New columns added to CSV:
- `content_score` (int 0-100): Content amount/structure score
- `design_score` (int 0-100): Visual design quality from GPT-4o
- `total_grade_score` (int 0-100): Weighted composite score
- `letter_grade` (str): A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F
- `grade_analysis` (str): Human-readable summary, e.g. "Great design, Poor content, Good performance"
- `weak_areas` (str): Comma-separated list, e.g. "content, performance"
- `strong_areas` (str): Comma-separated list, e.g. "design"
- `screenshot_path` (str): Relative path to screenshot file
- `grader_error` (str): Error message if grading failed (empty if success)

### Module Structure

**File**: `/Users/shreyaspaul/code/outreach_signals/scripts/website_grader.py`

**Key Functions/Classes**:

```python
def normalize_url(url: str) -> str:
    """Ensure URL has proper scheme (reuse from existing scripts)."""

def clean_domain(url: str) -> str:
    """Extract clean domain name for screenshot filename."""
    # e.g., "https://example.com/path" → "example_com"

def capture_screenshot_and_content(url: str, screenshot_dir: Path) -> dict:
    """
    Capture screenshot and extract content metrics using Playwright.

    Returns:
        {
            'screenshot_path': str,
            'word_count': int,
            'h1_count': int,
            'h2_count': int,
            'h3_count': int,
            'section_count': int,
            'paragraph_count': int,
            'nav_links': dict,  # {features: bool, pricing: bool, ...}
            'error': str or None
        }
    """

def score_content_amount(metrics: dict) -> int:
    """
    Score content amount/structure from 0-100.

    Scoring rubric:
    - Base score from word count (0-95 points)
    - Bonuses for structure: headings (+8), sections (+6), paragraphs (+6)
    - Navigation bonus: up to +10 for complete nav (pricing, features, docs, etc.)
    - Penalty: cap at 80 if missing h1 or h2s

    Returns: int 0-100
    """

def analyze_design_with_vision(screenshot_path: str, url: str, api_key: str) -> dict:
    """
    Analyze website design using GPT-4o vision.

    System prompt: "You are a senior design director at a top-tier design studio..."

    Returns:
        {
            'design_score': int 0-100,
            'comment': str,
            'error': str or None
        }
    """

def calculate_total_score(performance: int, content: int, design: int) -> dict:
    """
    Calculate weighted total and letter grade.

    Weights:
    - Performance: 30% (critical for conversions)
    - Content: 40% (core messaging)
    - Design: 30% (professionalism)

    Letter grades:
    - A+ (95-100), A (90-94), A- (85-89)
    - B+ (80-84), B (75-79), B- (70-74)
    - C+ (65-69), C (60-64), C- (55-59)
    - D+ (50-54), D (45-49), D- (40-44)
    - F (0-39)

    Returns:
        {
            'total_score': int,
            'letter_grade': str
        }
    """

def analyze_deviations(performance: int, content: int, design: int) -> dict:
    """
    Identify strong and weak areas based on score deviations.

    Thresholds:
    - Excellent: 80+
    - Good: 65-79
    - Average: 50-64
    - Poor: 35-49
    - Very Poor: 0-34

    Deviation logic:
    - Weak area: Score is 15+ points below average of other two
    - Strong area: Score is 15+ points above average of other two
    - OR: Absolute thresholds (Weak < 50, Strong >= 80)

    Returns:
        {
            'grade_analysis': str,  # "Excellent design, Poor content, Good performance"
            'weak_areas': str,      # "content"
            'strong_areas': str     # "design"
        }
    """

def grade_website(url: str, pagespeed_mobile: int = None, screenshot_dir: Path = None,
                  openai_api_key: str = None) -> dict:
    """
    Main grading function - orchestrates all steps.

    Returns complete grading result dict with all output columns.
    """

def process_csv(input_path: str, output_path: str = None, screenshot_dir: str = None,
                openai_api_key: str = None, delay: float = 2.0, limit: int = None) -> pd.DataFrame:
    """
    Process CSV file and add grading columns.

    Args:
        input_path: Path to input CSV
        output_path: Optional output path (defaults to input_graded.csv)
        screenshot_dir: Directory for screenshots (defaults to /screenshots)
        openai_api_key: OpenAI API key (reads from env if not provided)
        delay: Seconds between requests (rate limiting)
        limit: Optional limit for testing

    Returns: DataFrame with grading columns added
    """

if __name__ == "__main__":
    # CLI argument parsing with argparse
    # Supports: input, --output, --screenshot-dir, --api-key, --delay, --limit
```

**Integration Points with Orchestrator**:

In `orchestrator.py`, add:
```python
from website_grader import grade_website

# In run_enrichment() function, after traffic check:
if not skip_grader:
    print(f"\n{'='*60}")
    print("WEBSITE GRADING")
    print(f"{'='*60}\n")

    grader_results = []
    screenshot_dir = project_root / 'screenshots'
    screenshot_dir.mkdir(exist_ok=True)

    for idx, row in df.iterrows():
        url = row['Website']
        pagespeed_mobile = mobile_results[idx]['score']  # Reuse existing data
        company = row.get('Company Name', 'Unknown')

        print(f"[{idx + 1}/{total}] Grading {company}...")
        result = grade_website(url, pagespeed_mobile, screenshot_dir)
        grader_results.append(result)

        if result['error']:
            print(f"  Error: {result['error']}")
        else:
            print(f"  Grade: {result['letter_grade']} ({result['total_grade_score']}/100)")
            print(f"  {result['grade_analysis']}")

        time.sleep(delay)

    # Add columns to DataFrame
    df['content_score'] = [r.get('content_score') for r in grader_results]
    df['design_score'] = [r.get('design_score') for r in grader_results]
    df['total_grade_score'] = [r.get('total_grade_score') for r in grader_results]
    df['letter_grade'] = [r.get('letter_grade', '') for r in grader_results]
    df['grade_analysis'] = [r.get('grade_analysis', '') for r in grader_results]
    df['weak_areas'] = [r.get('weak_areas', '') for r in grader_results]
    df['strong_areas'] = [r.get('strong_areas', '') for r in grader_results]
    df['screenshot_path'] = [r.get('screenshot_path', '') for r in grader_results]
    df['grader_error'] = [r.get('error', '') for r in grader_results]
```

Add CLI argument:
```python
parser.add_argument('--skip-grader', action='store_true',
                    help='Skip website grading (saves OpenAI API costs)')
```

### Error Handling

**Expected Failure Modes**:

1. **Page Load Timeout**
   - Cause: Slow website, network issues
   - Handling: 30s timeout → return error, continue to next site
   - Fallback: All scores = None, grade = "F", error message stored

2. **Screenshot Capture Failure**
   - Cause: Page crash, rendering issues
   - Handling: Catch exception, log error
   - Fallback: Skip design analysis, use content + performance only

3. **OpenAI API Rate Limit / Error**
   - Cause: Rate limit (500 req/min for GPT-4o), network issues
   - Handling: Exponential backoff (3 retries: 2s, 5s, 10s)
   - Fallback: design_score = None, note in error column

4. **OpenAI JSON Parse Failure**
   - Cause: Model returns non-JSON or malformed JSON
   - Handling: Regex extraction fallback, look for numbers in text
   - Ultimate fallback: design_score = 50 (neutral)

5. **Missing PageSpeed Data**
   - Cause: Running grader standalone without prior orchestrator run
   - Handling: Default to 50 (neutral) for performance score
   - Note: Log warning, continue grading

6. **Invalid URL / Connection Error**
   - Cause: Malformed URL, site down
   - Handling: Return error immediately, don't attempt screenshot
   - Fallback: All scores = None, error message stored

**Retry Strategy**:
- Playwright navigation: No retry (already has 30s timeout)
- OpenAI API: 3 retries with exponential backoff (2s, 5s, 10s)
- Screenshot save: No retry (fail fast)

**User-Facing Error Messages**:
```python
ERROR_MESSAGES = {
    'timeout': 'Page load timeout (30s)',
    'screenshot_failed': 'Screenshot capture failed',
    'openai_rate_limit': 'OpenAI API rate limit',
    'openai_error': 'OpenAI API error',
    'connection_error': 'Connection failed',
    'invalid_url': 'Invalid URL',
    'browser_crash': 'Browser crashed',
}
```

### Configuration

**Environment Variables** (`.env`):
```bash
OPENAI_API_KEY=sk-...           # Required for design analysis
PAGESPEED_API_KEY=AIza...       # Already configured
```

**Default Values**:
```python
DEFAULT_SCREENSHOT_DIR = Path(__file__).parent.parent / 'screenshots'
DEFAULT_VIEWPORT = {'width': 1366, 'height': 900}  # Standard laptop resolution
DEFAULT_TIMEOUT = 30000  # 30 seconds
DEFAULT_DELAY = 2.0      # Seconds between requests
DEFAULT_PERFORMANCE_SCORE = 50  # If pagespeed_mobile missing

# Scoring weights
WEIGHT_PERFORMANCE = 0.30
WEIGHT_CONTENT = 0.40
WEIGHT_DESIGN = 0.30

# Deviation thresholds
DEVIATION_THRESHOLD = 15  # Points difference to flag as weak/strong
THRESHOLD_EXCELLENT = 80
THRESHOLD_GOOD = 65
THRESHOLD_AVERAGE = 50
THRESHOLD_POOR = 35
```

**API Keys / Credentials**:
- OpenAI API key stored in `.env` as `OPENAI_API_KEY`
- Loaded via `python-dotenv`
- If missing: script should error immediately with clear message

## Edge Cases & Considerations

### Edge Cases

1. **Single-Page Apps (SPAs) with Lazy Loading**
   - Issue: Initial HTML may be sparse, content loads via JavaScript
   - Handling: Wait for `networkidle` state (15s max) after initial load
   - Fallback: If still low word count, proceed with scoring (will be penalized fairly)

2. **Password-Protected / Login-Required Pages**
   - Issue: Can't access actual content
   - Handling: Detect auth pages by looking for login forms, 401/403 status
   - Result: Error out, note "Authentication required" in error column

3. **Very Long Pages (100+ screens)**
   - Issue: Full-page screenshot could be huge (memory/disk)
   - Handling: Set max screenshot height (10,000px) to prevent crashes
   - Impact: Design analysis still valid (captures hero + key sections)

4. **Sites with Cookie Banners / Popups**
   - Issue: Obscure content in screenshot
   - Handling: Accept as-is (most modern sites have this)
   - Future: Could add popup dismissal logic (complicated, out of scope for v1)

5. **Non-English Websites**
   - Issue: GPT-4o might score differently for non-English design
   - Handling: GPT-4o is multilingual, should assess design objectively
   - Note: Content word count still works universally

6. **Redirects (www → non-www, http → https)**
   - Issue: Playwright follows redirects by default
   - Handling: Allow redirects (correct behavior), use final URL for screenshot filename
   - Note: Clean domain name for filename to avoid duplicates

7. **Websites with Very Low Scores (all < 40)**
   - Issue: May indicate site is broken or non-functional
   - Handling: Flag in output, could add "site_appears_broken" boolean
   - Use case: Filter out for outreach (too dysfunctional to help)

8. **Identical Scores Across All Dimensions**
   - Issue: Deviation logic might not trigger
   - Handling: If all scores within 10 points, analysis = "Consistent quality across all areas"
   - Result: weak_areas and strong_areas both empty

### Performance Considerations

1. **Playwright Browser Overhead**
   - Impact: ~1-2 GB RAM per browser instance
   - Mitigation: Launch and close browser per request (not persistent)
   - Tradeoff: Slower but memory-safe for batch processing

2. **Screenshot Storage**
   - Concern: 10MB/screenshot × 135 sites = ~1.4 GB disk usage
   - Mitigation: Store as compressed PNG (typically 2-5 MB)
   - Cleanup: Add optional `--cleanup-screenshots` flag for post-processing

3. **OpenAI API Latency**
   - Typical: 3-10 seconds per vision API call
   - Total: 135 sites × 8s avg = ~18 minutes of API calls
   - Mitigation: This is unavoidable; inform user of expected runtime

4. **Batch Processing Time Estimate**:
   - Per site: ~15-25 seconds (page load 5s + screenshot 2s + content 1s + OpenAI 8s + delays)
   - 135 sites: ~35-55 minutes total
   - Display progress bar to user

### Rate Limiting Strategies

1. **OpenAI API Limits**:
   - GPT-4o: 500 requests/min, 800,000 tokens/min (Tier 2+)
   - Our usage: ~1 request every 2-3 seconds = 20-30 req/min (well under limit)
   - Strategy: No special rate limiting needed, but add 2s delay between sites

2. **Playwright / Website Rate Limiting**:
   - Risk: Some sites may block rapid automated access
   - Mitigation: 2-second delay between requests
   - User-Agent: Set realistic browser user-agent (already doing in Playwright)

3. **Concurrent Execution** (Future Enhancement):
   - v1: Sequential processing (simpler, safer)
   - v2: Could parallelize 3-5 browsers for 3-5x speedup
   - Tradeoff: More complex error handling, higher memory usage

## Testing Plan

### Unit Test Scenarios

```python
# test_website_grader.py

def test_clean_domain():
    assert clean_domain("https://example.com/path?query=1") == "example_com"
    assert clean_domain("http://www.example.com") == "example_com"
    assert clean_domain("example.com") == "example_com"

def test_score_content_amount():
    # Minimal content
    assert score_content_amount({
        'word_count': 50, 'h1_count': 0, 'h2_count': 0,
        'section_count': 0, 'paragraph_count': 0,
        'nav_links': {}
    }) < 20

    # Rich content
    assert score_content_amount({
        'word_count': 2000, 'h1_count': 2, 'h2_count': 5,
        'section_count': 6, 'paragraph_count': 15,
        'nav_links': {'features': True, 'pricing': True, 'docs': True}
    }) > 85

def test_calculate_total_score():
    result = calculate_total_score(80, 70, 90)
    assert result['total_score'] == 79  # 0.3*80 + 0.4*70 + 0.3*90
    assert result['letter_grade'] == 'B+'

def test_analyze_deviations():
    # Design strong, content weak
    result = analyze_deviations(70, 40, 85)
    assert 'content' in result['weak_areas']
    assert 'design' in result['strong_areas']
    assert 'Poor content' in result['grade_analysis']
    assert 'Excellent design' in result['grade_analysis']

    # Balanced scores
    result = analyze_deviations(70, 72, 68)
    assert result['weak_areas'] == ''
    assert result['strong_areas'] == ''
```

### Integration Test Scenarios

```python
# Manual integration tests (require real API keys)

def test_screenshot_capture_real_site():
    """Test capturing screenshot of a known-good site."""
    result = capture_screenshot_and_content("https://example.com", Path("./test_screenshots"))
    assert result['error'] is None
    assert Path(result['screenshot_path']).exists()
    assert result['word_count'] > 0

def test_openai_vision_real_call():
    """Test OpenAI vision analysis with real API."""
    # Use a pre-captured test screenshot
    result = analyze_design_with_vision("./test_assets/sample_site.png", "https://test.com", os.getenv('OPENAI_API_KEY'))
    assert result['error'] is None
    assert 0 <= result['design_score'] <= 100
    assert len(result['comment']) > 0

def test_full_grading_pipeline():
    """Test complete grading of a single site."""
    result = grade_website("https://example.com", pagespeed_mobile=75)
    assert result['error'] is None
    assert result['content_score'] is not None
    assert result['design_score'] is not None
    assert result['total_grade_score'] is not None
    assert result['letter_grade'] in ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F']
```

### Manual Verification Steps

1. **Test with 3-Site Sample CSV**:
   ```bash
   # Create test CSV
   echo "Company Name,Website\nTest 1,stripe.com\nTest 2,webflow.com\nTest 3,example.com" > test_grader.csv

   # Run grader standalone
   python scripts/website_grader.py test_grader.csv --limit 3

   # Verify:
   # - 3 screenshots created in /screenshots/
   # - Output CSV has all grading columns
   # - No errors in grader_error column
   # - Scores are reasonable (stripe.com should score high)
   ```

2. **Test with Orchestrator Integration**:
   ```bash
   # Run orchestrator with grader enabled
   python scripts/orchestrator.py app.csv --limit 5

   # Verify:
   # - Grading runs after traffic check
   # - All columns present in output
   # - Screenshots saved
   ```

3. **Test Error Handling**:
   ```bash
   # Create CSV with problem URLs
   echo "Company Name,Website\nInvalid,not-a-real-domain-12345.com\nTimeout,httpstat.us/524?sleep=35000" > test_errors.csv

   python scripts/website_grader.py test_errors.csv

   # Verify:
   # - Errors logged to grader_error column
   # - Script completes without crashing
   # - Remaining sites still processed
   ```

4. **Validate OpenAI Response Parsing**:
   ```bash
   # Check a few sites, manually inspect design_score and comments
   # Ensure scores are 0-100 range
   # Ensure comments are substantive (not "Parse error")
   ```

5. **Deviation Detection Accuracy**:
   ```bash
   # Manually review 5 graded sites
   # Check if weak_areas/strong_areas align with actual scores
   # Verify grade_analysis text makes sense
   ```

## Implementation Checklist

### Phase 1: Core Grading Functions (Simple - 2-3 hours)
- [ ] Create `scripts/website_grader.py` file
- [ ] Implement `normalize_url()` and `clean_domain()` helpers
- [ ] Implement `score_content_amount()` with full rubric
- [ ] Implement `calculate_total_score()` with letter grade mapping
- [ ] Implement `analyze_deviations()` with threshold logic
- [ ] Write unit tests for scoring functions

### Phase 2: Screenshot & Content Extraction (Medium - 3-4 hours)
- [ ] Add Playwright to requirements.txt
- [ ] Implement `capture_screenshot_and_content()` using Playwright
- [ ] Add page.evaluate() logic for content metrics
- [ ] Handle timeouts and errors gracefully
- [ ] Test screenshot capture on 3-5 real sites
- [ ] Verify content metrics accuracy (word count, headings)

### Phase 3: OpenAI Vision Integration (Medium - 2-3 hours)
- [ ] Add openai library to requirements.txt
- [ ] Implement `analyze_design_with_vision()` with GPT-4o
- [ ] Craft system prompt based on Node.js version
- [ ] Implement JSON parsing with fallback handling
- [ ] Add retry logic with exponential backoff
- [ ] Test with 3-5 real screenshots
- [ ] Validate score ranges and comment quality

### Phase 4: Main Grading Function (Medium - 2 hours)
- [ ] Implement `grade_website()` orchestration function
- [ ] Wire together: screenshot → content → design → scoring
- [ ] Handle missing pagespeed_mobile gracefully (default to 50)
- [ ] Return complete result dict with all output columns
- [ ] Test end-to-end on 3 sites

### Phase 5: CSV Processing (Simple - 1-2 hours)
- [ ] Implement `process_csv()` function
- [ ] Add progress output (similar to orchestrator style)
- [ ] Create /screenshots directory if missing
- [ ] Add all grading columns to DataFrame
- [ ] Save output CSV with timestamp
- [ ] Print summary stats (avg scores, grade distribution)

### Phase 6: CLI & Standalone Mode (Simple - 1 hour)
- [ ] Add argparse CLI with all arguments
- [ ] Support: input, --output, --screenshot-dir, --api-key, --delay, --limit
- [ ] Add helpful error messages for missing API key
- [ ] Test standalone execution: `python scripts/website_grader.py test.csv`

### Phase 7: Orchestrator Integration (Medium - 2-3 hours)
- [ ] Add `--skip-grader` argument to orchestrator
- [ ] Import `grade_website` function in orchestrator
- [ ] Add grading section after traffic check
- [ ] Reuse pagespeed_mobile scores from earlier in pipeline
- [ ] Add grading columns to DataFrame
- [ ] Update orchestrator summary to include grading stats
- [ ] Test full orchestrator run with grader enabled

### Phase 8: Testing & Validation (Complex - 3-4 hours)
- [ ] Run unit tests, ensure all pass
- [ ] Test standalone mode on 5-site sample
- [ ] Test orchestrator integration on 10-site sample
- [ ] Test error cases (invalid URLs, timeouts, API errors)
- [ ] Validate deviation detection on diverse scores
- [ ] Review screenshots for quality
- [ ] Review design scores/comments for reasonableness
- [ ] Check CSV output format and column names

### Phase 9: Documentation & Polish (Simple - 1 hour)
- [ ] Update CLAUDE.md with grader documentation
- [ ] Add example usage to README section
- [ ] Document output columns in CLAUDE.md
- [ ] Add cost estimate (OpenAI API usage)
- [ ] Add expected runtime estimate
- [ ] Create example output CSV snippet for reference

## Future Enhancements

### v2 Enhancements (Post-MVP)

1. **Parallel Processing**:
   - Launch 3-5 Playwright browsers concurrently
   - Speed up batch grading by 3-5x
   - Complexity: Medium (need semaphore/queue management)

2. **Screenshot Storage to S3**:
   - Optional `--upload-screenshots` flag
   - Store screenshots in S3 for long-term access
   - Include S3 URLs in CSV output
   - Complexity: Simple (boto3 integration)

3. **Content Quality Scoring (GPT-4o)**:
   - Add back the 80% amount / 20% quality split from Node version
   - Extract page text sample, send to GPT-4o for quality analysis
   - Tradeoff: Higher API costs vs. more nuanced content scoring
   - Complexity: Simple (API call + prompt engineering)

4. **Historical Trend Tracking**:
   - Store grading results in database (SQLite/Postgres)
   - Re-grade sites monthly, track improvements/regressions
   - Use for outreach follow-up ("Your score improved from C to B!")
   - Complexity: Medium (database schema + migration logic)

5. **Interactive HTML Report**:
   - Generate HTML report with screenshots embedded
   - Visual charts showing score distributions
   - Click-through to see individual site analysis
   - Complexity: Medium (templating + static site generation)

6. **Competitive Benchmarking**:
   - For each industry vertical, calculate avg scores
   - Show "Your site scores 65 vs. industry avg of 78"
   - Requires: Industry classification in source data
   - Complexity: Medium (statistical analysis + data grouping)

7. **Smart Popup/Cookie Banner Dismissal**:
   - Detect and dismiss common cookie banners before screenshot
   - Use Playwright's auto-wait + click logic
   - Libraries: Could integrate `playwright-cookies` or similar
   - Complexity: Complex (many banner variations, fragile)

8. **Mobile Screenshot Option**:
   - Capture mobile viewport (375x667) in addition to desktop
   - Separate mobile_design_score
   - Useful for highlighting mobile UX issues
   - Complexity: Simple (just viewport parameter change)

9. **Accessibility Scoring**:
   - Use axe-core via Playwright to check WCAG compliance
   - Add accessibility_score (0-100) based on violations
   - Separate weak area: "accessibility"
   - Complexity: Medium (axe integration + scoring rubric)

10. **Cost Optimization: Design Caching**:
    - Cache design scores by URL + screenshot hash
    - Skip re-analysis if screenshot unchanged
    - Useful for re-running grader after fixing other issues
    - Complexity: Simple (hash comparison + JSON cache file)

### Scoring Weight Experimentation

After collecting data from 50+ graded sites, consider A/B testing different weight distributions:

**Current**: Performance 30%, Content 40%, Design 30%

**Alternative A - Performance-Heavy** (B2C e-commerce focus):
- Performance 50%, Content 25%, Design 25%
- Rationale: Page speed directly impacts conversion rates

**Alternative B - Content-Heavy** (B2B SaaS focus):
- Performance 20%, Content 50%, Design 30%
- Rationale: Clear value prop and messaging matter most for B2B

**Alternative C - Design-Heavy** (Brand/agency focus):
- Performance 20%, Content 30%, Design 50%
- Rationale: Visual identity is paramount for creative businesses

Implementation: Make weights configurable via CLI arguments or config file.

---

## Appendix: Scoring Rubric Details

### Content Amount Scoring (0-100)

**Base Score by Word Count**:
- 0-79 words: 10 points (sparse)
- 80-199 words: 20 points (minimal)
- 200-399 words: 35 points (light)
- 400-799 words: 55 points (moderate)
- 800-1499 words: 75 points (substantial)
- 1500-2999 words: 90 points (rich)
- 3000+ words: 95 points (very comprehensive)

**Structure Bonuses** (cumulative):
- H1 present: +8 points
- 2+ H2s: +6 points
- 3+ sections: +6 points
- 10+ paragraphs: +6 points

**Navigation Bonus** (up to +10):
- Each key nav link present: +2 points
- Links: features, pricing, docs, blog, careers, contact, about

**Penalties**:
- If score > 80 but missing H1 or H2s: cap at 80 (structure matters)

**Maximum**: 100 (after bonuses and penalties)

### Design Scoring (0-100)

**GPT-4o Vision Prompt**:
```
System: You are a senior design director at a top-tier design studio.
Evaluate ONLY visual design professionalism from the screenshot.
Ignore content quantity.
Be critical.
Score 0-100 for professional polish, sophistication, hierarchy, typography,
spacing, visual clarity, and brand craft.
Return strict JSON: {"design_score": <0-100>, "comment": "<one detailed sentence>"}

User: Analyze the visual design quality from a professional design standpoint only.
Consider: sophistication, intentionality, polish, hierarchy, typography, spacing,
visual clarity, brand craft.
Be critical: simple/minimal ≠ professional by default.
URL: {url}
Output JSON: {"design_score": <0-100>, "comment": "<one detailed sentence>"}
```

**Expected Score Ranges** (based on Node.js grader data):
- Premium SaaS (Stripe, Webflow): 85-95
- Good startups (YC companies): 70-85
- Average SMB sites: 50-70
- DIY / template sites: 30-50
- Broken / very poor: 0-30

### Letter Grade Mapping

| Score | Grade | Interpretation |
|-------|-------|----------------|
| 95-100 | A+ | Exceptional, industry-leading |
| 90-94 | A | Excellent, highly professional |
| 85-89 | A- | Very good, above average |
| 80-84 | B+ | Good, solid quality |
| 75-79 | B | Good, meets expectations |
| 70-74 | B- | Decent, minor improvements needed |
| 65-69 | C+ | Acceptable, noticeable gaps |
| 60-64 | C | Mediocre, needs improvement |
| 55-59 | C- | Below average, significant issues |
| 50-54 | D+ | Poor, major improvements needed |
| 45-49 | D | Very poor, multiple critical issues |
| 40-44 | D- | Failing, severe problems |
| 0-39 | F | Unacceptable, likely broken |

### Deviation Analysis Examples

**Example 1 - Design Strong, Content Weak**:
- Performance: 70
- Content: 40
- Design: 85
- Average of others: (70+85)/2 = 77.5
- Content deviation: 40 - 77.5 = -37.5 (weak!)
- Design deviation: 85 - ((70+40)/2) = +30 (strong!)
- **Output**:
  - weak_areas: "content"
  - strong_areas: "design"
  - grade_analysis: "Excellent design, Poor content, Good performance"

**Example 2 - Balanced Scores**:
- Performance: 72
- Content: 70
- Design: 75
- All within 5 points → no significant deviation
- **Output**:
  - weak_areas: ""
  - strong_areas: ""
  - grade_analysis: "Consistent quality across all areas"

**Example 3 - All Poor**:
- Performance: 35
- Content: 30
- Design: 38
- All below 50 → all weak
- **Output**:
  - weak_areas: "performance, content, design"
  - strong_areas: ""
  - grade_analysis: "Very poor performance, Very poor content, Very poor design"

---

## Cost Estimates

### OpenAI API Costs (GPT-4o Vision)

**Pricing** (as of Jan 2025):
- GPT-4o: $2.50 per 1M input tokens, $10.00 per 1M output tokens
- Vision: Images count as ~765-1000 tokens depending on detail level

**Per-Site Cost**:
- Input: ~1000 tokens (image) + ~100 tokens (prompt) = 1100 tokens
- Output: ~50 tokens (JSON response)
- Cost: (1100 * $2.50 / 1M) + (50 * $10 / 1M) = **$0.0028 per site** (~0.3 cents)

**Batch Estimates**:
- 10 sites: $0.03
- 100 sites: $0.28
- 135 sites (full app.csv): **$0.38**
- 1000 sites: $2.80

**Conclusion**: Very affordable. Even grading 1000 sites costs less than $3.

### Runtime Estimates

**Per-Site Breakdown**:
- Playwright browser launch: 2-3s
- Page load (wait for networkidle): 3-8s
- Screenshot capture: 1-2s
- Content extraction: 0.5s
- OpenAI API call: 3-10s (avg 6s)
- Rate limiting delay: 2s
- **Total: 12-26 seconds per site (avg ~18s)**

**Batch Estimates**:
- 10 sites: 3-4 minutes
- 100 sites: 30-43 minutes
- 135 sites (full app.csv): **40-58 minutes**

**Parallelization Potential** (Future):
- With 5 concurrent browsers: reduce to ~8-12 minutes for 135 sites

---

## Questions Addressed

### 1. How should we define thresholds for "good", "average", "poor"?

**Answer**: Using 5-tier system aligned with letter grades:

- **Excellent**: 80-100 (A/B+ range) - Professional quality
- **Good**: 65-79 (B/C+ range) - Solid, meets expectations
- **Average**: 50-64 (C/D+ range) - Acceptable but room for improvement
- **Poor**: 35-49 (D/F range) - Significant issues
- **Very Poor**: 0-34 (F range) - Critical problems

These align with common grading scales and are intuitive for users.

### 2. What's the best scoring weight distribution?

**Answer**: **Performance 30%, Content 40%, Design 30%**

**Rationale**:
- **Content 40%** - Core value proposition, messaging, and information architecture are most important for conversion and SEO
- **Performance 30%** - Critical for user experience and SEO, but can be technically fixed without redesign
- **Design 30%** - Important for trust and brand perception, but subjective; good content can convert with mediocre design

This distribution prioritizes the "what" (content) over the "how" (design/performance), which aligns with B2B SaaS buying behavior.

**Alternative for different use cases**: Make weights configurable in v2.

### 3. How to structure the deviation detection logic?

**Answer**: **Hybrid approach - relative deviation + absolute thresholds**

**Logic**:
1. Calculate average of the other two dimensions for each dimension
2. If dimension score is 15+ points below average → WEAK
3. If dimension score is 15+ points above average → STRONG
4. ALSO apply absolute thresholds:
   - Score < 50 → WEAK (regardless of others)
   - Score >= 80 → STRONG (regardless of others)
5. Generate descriptive labels based on thresholds:
   - 80+: "Excellent"
   - 65-79: "Good"
   - 50-64: "Average"
   - 35-49: "Poor"
   - 0-34: "Very Poor"

**Example**: Performance 90, Content 45, Design 75
- Content avg of others: (90+75)/2 = 82.5
- Content deviation: 45 - 82.5 = -37.5 → WEAK
- Content also < 50 → WEAK (confirmed by absolute threshold)
- Result: weak_areas = "content", analysis = "Excellent performance, Poor content, Good design"

### 4. Should we store screenshots? If so, where?

**Answer**: **Yes, store locally in `/screenshots/` directory**

**Rationale**:
- **Debugging**: Useful to visually verify grading accuracy
- **Outreach**: Can reference specific visual issues in messages
- **Historical**: Track visual changes over time (future enhancement)
- **Cost**: Local storage is free (vs. S3 costs)
- **Privacy**: Keep prospect data local, not uploaded to third-party

**Filename Format**: `{clean_domain}.png` (e.g., `stripe_com.png`)

**Cleanup Strategy**:
- Keep screenshots by default
- Add optional `--cleanup-screenshots` flag to delete after grading (for batch runs where screenshots aren't needed)
- Document: ~2-5 MB per screenshot, 135 sites = ~270-675 MB total

**Future**: Add `--upload-to-s3` option for cloud storage with URL output.

### 5. How to integrate with orchestrator efficiently?

**Answer**: **Import `grade_website()` function, call after traffic check, reuse PageSpeed data**

**Efficiency Optimizations**:
1. **Reuse PageSpeed Mobile Score** - Already fetched earlier, pass directly to grader (saves 1 API call per site)
2. **Sequential Placement** - Run after all other checks so we have complete data
3. **Optional Execution** - `--skip-grader` flag for cost control
4. **Shared Screenshot Directory** - Use project-level `/screenshots/` directory
5. **Consistent Error Handling** - Follow same pattern as other enrichment scripts
6. **Progress Output** - Match orchestrator's output style for consistency

**Integration Pattern** (same as traffic_checker, pagespeed_checker):
```python
from website_grader import grade_website

# In run_enrichment():
if not skip_grader:
    grader_results = []
    for idx, row in df.iterrows():
        result = grade_website(url, pagespeed_mobile=mobile_results[idx]['score'])
        grader_results.append(result)

    # Add columns to DataFrame
    df['content_score'] = [r.get('content_score') for r in grader_results]
    # ... etc
```

**Runtime Impact**: Adds ~18s per site to orchestrator. For 135 sites, adds ~40-55 minutes. This is acceptable as grading is optional and highly valuable.

### 6. Any other improvements or considerations?

**Additional Considerations**:

1. **Progressive Enhancement**: Start simple (no GPT content quality), add later if needed
2. **Logging**: Add detailed logging for debugging (screenshot paths, API responses, errors)
3. **Resume Capability**: Check if screenshot exists before re-capturing (idempotent)
4. **Graceful Degradation**: If OpenAI fails, still grade based on performance + content only
5. **User Feedback Loop**: After grading 50+ sites, review results to tune thresholds/prompts
6. **Documentation**: Include example output in CLAUDE.md for reference
7. **Testing**: Create small test CSV (3-5 sites) for quick validation
8. **API Key Validation**: Check for OPENAI_API_KEY at startup, fail fast with clear message
9. **Screenshot Quality**: Use high-quality PNG compression (not lossy JPEG) for accurate design analysis
10. **Viewport Consistency**: Always use 1366×900 (standard laptop) for fair comparison across sites

**Edge Cases to Document**:
- Sites with aggressive bot detection (Cloudflare, etc.) → May fail, acceptable
- Sites requiring JavaScript to render (SPAs) → Playwright handles, but wait for networkidle
- Sites with animations/videos → Screenshot captures single frame, acceptable
- Sites with A/B testing → May get different variants on re-run, note as limitation

---

## Success Metrics

After implementation, validate success by:

1. **Accuracy**: Manually review 10 graded sites, verify scores align with human judgment
2. **Coverage**: >90% of sites successfully graded (error rate <10%)
3. **Performance**: Complete 135-site batch in <60 minutes
4. **Cost**: Total OpenAI API cost <$1 for 135 sites
5. **Usability**: Colleagues can run standalone grader with 1 command
6. **Integration**: Orchestrator runs without errors with grader enabled
7. **Actionability**: Grade analysis clearly identifies weak areas for outreach personalization

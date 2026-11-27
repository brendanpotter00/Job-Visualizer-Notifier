import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import { keyframes, useTheme } from '@mui/material/styles';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { WORDMARK_COLOR, WORDMARK_FONT_FAMILY, SIGNAL_GREEN } from '../../config/brand';
import { APP_TITLE } from '../../config/constants';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../constants/enrichment';
import { companyCategoryOptions } from '../../config/companyCategories';
import {
  getPostHogSessionId,
  trackOnboardingStep,
  trackOnboardingViewed,
} from '../../features/analytics/events';
import { useGetFacetsQuery } from '../../features/jobs/jobsApi';
import { savedFiltersPropagationActions } from '../../features/savedFilters/propagateSavedFilters';
import {
  savedFiltersApi,
  useCompleteOnboardingMutation,
  type OnboardingAnswers,
  type OnboardingResult,
} from '../../features/savedFilters/savedFiltersApi';
import { useSubcategoryRevealEnabled } from '../../features/settings/subcategoryReveal';
import { extractErrorMessage } from '../../lib/errors';
import { VISUALLY_HIDDEN_SX } from '../../lib/visuallyHidden';
import { ErrorState } from '../shared/ErrorDisplay';
import { CompanyTypeQuestion } from './CompanyTypeQuestion';
import { LevelQuestion } from './LevelQuestion';
import { LocationQuestion } from './LocationQuestion';
import { RoleQuestion } from './RoleQuestion';
import {
  EMPTY_ANSWERS,
  forBackend,
  ONBOARDING_QUESTIONS,
  ONBOARDING_SAVE_ERROR,
  ONBOARDING_STEP_COUNT,
  onboardingDocumentTitle,
  savedFiltersHaveAnswers,
  stepHasAnswer,
  toRequestAnswers,
  type OnboardingStep,
} from './onboardingModel';

const T = RESPONSIVE.onboarding;

/** One centered column on a desktop; the full width on a phone. */
const COLUMN_SX = { width: '100%', maxWidth: T.columnMaxWidth, mx: 'auto' } as const;
const FIELDSET_RESET_SX = { border: 0, m: 0, p: 0, minWidth: 0 } as const;

const selectKeywordLists = savedFiltersApi.endpoints.getKeywordLists.select();
const selectSavedFilters = savedFiltersApi.endpoints.getSavedFilters.select();

const fill = keyframes`
  from { width: var(--from); }
  to { width: var(--to); }
`;

const stepWidth = (step: number) => `${(((step + 1) / ONBOARDING_STEP_COUNT) * 100).toFixed(2)}%`;

/**
 * The 4px bar under "1/4". It fills one quarter per question and slides from the
 * last step's width to this one's (from empty when the questions open). It is
 * decoration: the counter beside Skip carries the words.
 */
function StepProgress({ step, fromStep }: { step: OnboardingStep; fromStep: number }) {
  return (
    <Box
      aria-hidden
      data-testid="onboarding-progress"
      sx={{
        display: 'block',
        height: 4,
        mt: '4px',
        borderRadius: '2px',
        bgcolor: 'divider',
        overflow: 'hidden',
      }}
    >
      <Box
        // A new element per step restarts the slide.
        key={step}
        data-testid="onboarding-progress-fill"
        sx={{
          height: '100%',
          width: stepWidth(step),
          borderRadius: '2px',
          bgcolor: 'text.primary',
          '--from': stepWidth(fromStep),
          '--to': stepWidth(step),
          animation: `${fill} .3s ease-out`,
          '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
      />
    </Box>
  );
}

/**
 * The question. Remounted per step (by key), so focus lands on it every time a
 * step opens — including the first, once the dialog's portal has mounted.
 */
function QuestionHeading({
  id,
  describedBy,
  children,
}: {
  id: string;
  describedBy: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus({ preventScroll: true });
  }, []);
  return (
    <Box
      component="h1"
      ref={ref}
      id={id}
      tabIndex={-1}
      aria-describedby={describedBy}
      sx={{
        m: 0,
        mt: '6px',
        mb: '20px',
        fontSize: T.questionFontSize,
        fontWeight: 500,
        letterSpacing: '-0.03em',
        lineHeight: 1.15,
        outline: 'none',
      }}
    >
      {children}
    </Box>
  );
}

export interface OnboardingFlowProps {
  /** False once the answers are saved: the dialog fades out, then `onExited`. */
  open: boolean;
  /** The answers are saved and the account is stamped. */
  onDone: (result: OnboardingResult) => void;
  /** A Skip could not be saved: close for this visit, and ask again on the next load. */
  onDismiss: () => void;
  /** The dialog has finished closing. */
  onExited: () => void;
}

/**
 * The first-sign-in questions: roles, levels, places, company types, one on
 * each screen.
 *
 * A full-screen dialog at every size, so nothing shows behind it. A black top
 * bar with the wordmark; under it a row that never scrolls, with "1/4" and
 * Skip over a progress bar; the question; and Back + Continue at the bottom
 * (Back is shown but disabled on question 1). Every question is optional and
 * Continue never waits for an answer. Back keeps the answers, because one
 * draft holds all four steps.
 *
 * Finish ("Show my jobs") and Skip both send the answers given so far in one
 * request, and so do Escape and any other close of the dialog (they count as
 * Skip). Once saved, the answers reach the live filters without a reload, and
 * if any were given the app lands on Recent Job Postings with them in its
 * filter fields. A Skip that fails to save still closes the questions, for
 * this visit only: the stamp stays unset, so they open again on the next load.
 */
export function OnboardingFlow({ open, onDone, onDismiss, onExited }: OnboardingFlowProps) {
  const theme = useTheme();
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [step, setStep] = useState<OnboardingStep>(0);
  // Where the progress bar slides from: -1 (empty) as the questions open.
  const [fromStep, setFromStep] = useState(-1);
  const [draft, setDraft] = useState<OnboardingAnswers>(EMPTY_ANSWERS);
  const [announcement, setAnnouncement] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [edge, setEdge] = useState(false);
  const [completeOnboarding] = useCompleteOnboardingMutation();
  const submitting = useRef(false);
  const viewed = useRef(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const counterId = useId();

  const { data: facets } = useGetFacetsQuery();
  const revealSubcategories = useSubcategoryRevealEnabled();
  const keywordLists = useAppSelector(selectKeywordLists).data;
  // Whether this backend knows company types: the saved-filters GET carries
  // `companyCategory` (`[]` included) only when it does. Facets cannot answer
  // this: they are edge-cached for a day.
  const backendKnowsCompanyType =
    useAppSelector(selectSavedFilters).data?.companyCategory !== undefined;
  const categories = facets?.categories ?? FALLBACK_CATEGORIES;
  const levels = facets?.levels ?? FALLBACK_LEVELS;
  // Same gate as the filter bars: the flag AND a non-empty catalog, with no
  // fallback list, so Software Engineering never opens into nothing.
  const subcategories = revealSubcategories ? (facets?.subcategories ?? []) : [];
  const companyTypes = companyCategoryOptions(facets);

  useEffect(() => {
    if (viewed.current) return;
    viewed.current = true;
    trackOnboardingViewed();
  }, []);

  // Name the step in the tab title while the questions are open, and put the
  // page's title back the moment they close. Keyed on `open`, not on mount: a
  // Skip that fails to save closes the dialog but leaves this component
  // mounted (the stamp is still null), and the step title must not outlive it
  // (WCAG 2.4.2 Page Titled).
  useEffect(() => {
    if (!open) return;
    const previous = document.title;
    return () => {
      document.title = previous;
    };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    document.title = onboardingDocumentTitle(step, APP_TITLE);
  }, [open, step]);

  // The bottom bar's top hairline shows only while the question scrolls under it.
  const updateEdge = useCallback(() => {
    const body = bodyRef.current;
    if (!body) return;
    setEdge(body.scrollTop + body.clientHeight < body.scrollHeight - 1);
  }, []);
  // A callback ref, not an effect: the dialog mounts its content through a
  // portal a render after this component, so an effect here would run before
  // the body exists. The observer re-measures when the window or the question
  // (its content column) changes size.
  const attachBody = useCallback(
    (body: HTMLDivElement | null) => {
      bodyRef.current = body;
      if (!body || typeof ResizeObserver === 'undefined') return undefined;
      const observer = new ResizeObserver(() => updateEdge());
      observer.observe(body);
      if (body.firstElementChild) observer.observe(body.firstElementChild);
      return () => observer.disconnect();
    },
    [updateEdge]
  );

  const goTo = (next: OnboardingStep) => {
    setFromStep(step);
    setStep(next);
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
  };

  const submit = async (skipped: boolean) => {
    // A double tap, or Escape during the request, sends one request.
    if (submitting.current) return;
    submitting.current = true;
    setError(null);
    try {
      const result = await completeOnboarding(
        // An older backend (the deploy window) gets no company types and a
        // step clamped to 3; it would 422 either. The 4th answer is lost then.
        forBackend(
          {
            ...toRequestAnswers(draft),
            skipped,
            step: (step + 1) as 1 | 2 | 3 | 4,
            sessionId: getPostHogSessionId(),
          },
          backendKnowsCompanyType
        )
      ).unwrap();
      // Saved-filter hydration runs once per sign-in and has already run, so
      // the answers are pushed the way a Saved Filters save pushes them: the
      // cache first, then the live filters of both pages.
      await dispatch(
        savedFiltersApi.util.upsertQueryData('getSavedFilters', undefined, result.savedFilters)
      );
      savedFiltersPropagationActions(result.savedFilters, keywordLists ?? [], {
        listsLoaded: Boolean(keywordLists),
      }).forEach((action) => dispatch(action));
      if (savedFiltersHaveAnswers(result.savedFilters)) navigate(ROUTES.RECENT_JOBS);
      onDone(result);
    } catch (err) {
      submitting.current = false;
      if (skipped) {
        onDismiss();
        return;
      }
      setError(extractErrorMessage(err, ONBOARDING_SAVE_ERROR));
    }
  };

  const next = () => {
    trackOnboardingStep({ step: step + 1, answered: stepHasAnswer(draft, step) });
    if (step < ONBOARDING_STEP_COUNT - 1) {
      goTo((step + 1) as OnboardingStep);
    } else {
      void submit(false);
    }
  };

  const back = () => {
    if (step > 0) goTo((step - 1) as OnboardingStep);
  };

  const last = step === ONBOARDING_STEP_COUNT - 1;
  const question = ONBOARDING_QUESTIONS[step];

  return (
    <Dialog
      open={open}
      fullScreen
      // No fade IN: the questions take the place of the loading screen
      // `RootLayout` holds while it waits for the answer (`useOnboardingHold`).
      // A fade would show the page through the half-transparent dialog for a
      // moment — the very "page first, then the questions" jump that hold
      // removes. The fade OUT stays: `onExited` waits for it.
      transitionDuration={{ enter: 0, exit: theme.transitions.duration.leavingScreen }}
      // Escape (and any other close) counts as Skip.
      onClose={() => void submit(true)}
      aria-labelledby={titleId}
      slotProps={{
        paper: {
          sx: {
            bgcolor: 'common.white',
            color: 'text.primary',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          },
        },
        transition: { onExited },
      }}
    >
      {/* The black top bar: the wordmark only, in the app bar's type. */}
      <Box
        sx={{
          height: T.barHeight,
          flex: 'none',
          display: 'flex',
          alignItems: 'center',
          px: T.gutterX,
          bgcolor: 'common.black',
          color: WORDMARK_COLOR,
        }}
      >
        <Box
          component="span"
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 1,
            fontFamily: WORDMARK_FONT_FAMILY,
            fontWeight: 700,
            fontSize: '20px',
            letterSpacing: '-0.03em',
            lineHeight: 1,
          }}
        >
          {APP_TITLE}
          <Box
            component="span"
            aria-hidden
            sx={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              bgcolor: SIGNAL_GREEN,
              boxShadow: '0 0 8px rgba(47,143,63,.6)',
            }}
          />
        </Box>
      </Box>

      {/* The step row: "1/4" and Skip, then the bar. It never scrolls away. */}
      <Box sx={{ flex: 'none', px: T.gutterX, pt: T.stepRowPaddingTop }}>
        <Box sx={COLUMN_SX}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: '2px', minHeight: 44 }}>
            <Box
              component="span"
              aria-hidden
              sx={{
                fontSize: '0.875rem',
                lineHeight: 1,
                color: 'text.secondary',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {step + 1}/{ONBOARDING_STEP_COUNT}
            </Box>
            <Box component="span" id={counterId} sx={VISUALLY_HIDDEN_SX}>
              Question {step + 1} of {ONBOARDING_STEP_COUNT}
            </Box>
            <Box sx={{ flex: 1 }} />
            <Button
              variant="text"
              onClick={() => void submit(true)}
              sx={{
                minWidth: 0,
                minHeight: 44,
                pl: '10px',
                pr: '6px',
                mr: '-6px',
                color: 'text.primary',
                fontSize: '0.9375rem',
                fontWeight: 500,
              }}
            >
              Skip
            </Button>
          </Box>
          <StepProgress step={step} fromStep={fromStep} />
        </Box>
      </Box>

      <Box
        ref={attachBody}
        onScroll={updateEdge}
        sx={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          overscrollBehavior: 'contain',
          px: T.gutterX,
          pt: T.bodyPaddingTop,
          pb: T.bodyPaddingBottom,
          scrollPaddingBottom: '96px',
        }}
      >
        <Box sx={COLUMN_SX}>
          <Box component="fieldset" sx={FIELDSET_RESET_SX}>
            <Box component="legend" sx={{ p: 0, width: '100%' }}>
              <QuestionHeading key={step} id={titleId} describedBy={counterId}>
                {question.title}
              </QuestionHeading>
            </Box>
            {step === 0 && (
              <RoleQuestion
                categories={categories}
                subcategories={subcategories}
                category={draft.category}
                subcategory={draft.subcategory}
                onChange={({ category, subcategory }) =>
                  setDraft((d) => ({ ...d, category, subcategory }))
                }
                onAnnounce={setAnnouncement}
              />
            )}
            {step === 1 && (
              <LevelQuestion
                levels={levels}
                level={draft.level}
                onChange={(level) => setDraft((d) => ({ ...d, level }))}
              />
            )}
            {step === 2 && (
              <LocationQuestion
                locations={draft.locations}
                onChange={(locations) => setDraft((d) => ({ ...d, locations }))}
                onAnnounce={setAnnouncement}
              />
            )}
            {step === 3 && (
              <CompanyTypeQuestion
                options={companyTypes}
                companyCategory={draft.companyCategory ?? []}
                onChange={(companyCategory) => setDraft((d) => ({ ...d, companyCategory }))}
              />
            )}
          </Box>
        </Box>
      </Box>

      {/* Back + Continue. The hairline shows only while content scrolls under it. */}
      <Box
        data-testid="onboarding-footer"
        data-edge={edge ? 'true' : 'false'}
        sx={{
          flex: 'none',
          borderTop: '1px solid',
          borderTopColor: edge ? 'divider' : 'transparent',
          transition: 'border-color .15s',
          bgcolor: 'common.white',
          px: T.gutterX,
          pt: T.footPaddingTop,
          pb: T.footPaddingBottom,
          '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
        }}
      >
        <Box sx={COLUMN_SX}>
          {error && (
            <Box sx={{ mb: 1.5 }}>
              <ErrorState inline message={error} />
            </Box>
          )}
          <Box sx={{ display: 'flex', gap: '10px' }}>
            <Button
              variant="outlined"
              disabled={step === 0}
              onClick={back}
              sx={{
                flex: 'none',
                minWidth: 96,
                minHeight: 48,
                fontSize: '1rem',
                color: 'text.primary',
                borderColor: 'text.primary',
                '&:hover': { borderColor: 'text.primary' },
              }}
            >
              Back
            </Button>
            <Button
              variant="contained"
              disableElevation
              onClick={next}
              sx={{
                flex: 1,
                minHeight: 48,
                fontSize: '1rem',
                bgcolor: 'common.black',
                color: 'common.white',
                '&:hover': { bgcolor: 'primary.light' },
              }}
            >
              {last ? 'Show my jobs' : 'Continue'}
            </Button>
          </Box>
        </Box>
      </Box>

      <Box aria-live="polite" sx={VISUALLY_HIDDEN_SX}>
        {announcement}
      </Box>
    </Dialog>
  );
}

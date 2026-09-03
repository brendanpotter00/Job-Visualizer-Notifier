import { useEffect, useRef, useState } from 'react';
import { Box, Button, Container, IconButton, Link } from '@mui/material';
import { alpha } from '@mui/material/styles';
import GitHubIcon from '@mui/icons-material/GitHub';
import { Link as RouterLink } from 'react-router-dom';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';

interface LandingHeaderProps {
  content: LandingContent;
}

/**
 * The shared landing header — wordmark left, two quiet nav links beside it, and
 * the source-code mark + Log in / Sign up on the right. Every label and target
 * comes from `content.header`; this file only decides how they look.
 *
 * Placement contract: render it as the FIRST child of the page's root box,
 * OUTSIDE any `overflow: hidden` wrapper. `position: sticky` sticks to the
 * nearest scrolling ancestor (the page's inner 100dvh scroller) but only while
 * its own containing block is in view — so nesting it inside Gravity's clipped
 * hero wrapper would scroll it away with the hero. Sitting
 * above the hero also means the falling-logo canvas starts below the bar, so
 * the pile never occludes the links and the pointer-repel keeps the full canvas.
 *
 * Auth targets are the mock ACCOUNT route the hero CTAs already use. Wiring
 * these to real Auth0 login/signup is promotion-time work, not prototype work.
 */
export function LandingHeader({ content }: LandingHeaderProps) {
  const { header } = content;
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const [scrolled, setScrolled] = useState(false);

  // An IntersectionObserver on the 1px sentinel above the bar, NOT a scroll
  // listener: the flag flips twice for a whole page of scrolling instead of
  // once per frame, so nothing re-renders while the user is actually moving.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (entry) setScrolled(!entry.isIntersecting);
    });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      {/*
        Sentinel: in view => the page is at the top => the bar stays transparent
        over the hero. Out of view => opaque + hairline. No `root` is passed,
        because an implicit-root observer is still clipped by the inner
        overflow ancestor, which is exactly the scroller we care about.
      */}
      <Box ref={sentinelRef} aria-hidden data-testid="landing-header-sentinel" sx={{ height: '1px' }} />
      <Box
        component="header"
        data-testid="landing-header"
        data-scrolled={String(scrolled)}
        sx={{
          position: 'sticky',
          top: 0,
          // Swallows the sentinel's 1px so the bar still starts flush with the
          // top of the page rather than one pixel down.
          mt: '-1px',
          // Above the Gravity canvas and the HeroTrendline, which are plain
          // absolutely-positioned layers at auto z-index: once the bar goes
          // opaque, hero content has to pass UNDER it.
          zIndex: 10,
          borderBottom: '1px solid',
          borderColor: scrolled ? 'divider' : 'transparent',
          // Not fully opaque: the blurred page showing faintly through keeps
          // the bar from reading as a second, heavier app chrome. 0.94 rather
          // than the usual ~0.9 because what passes under it in Gravity is a
          // wall of saturated brand logos, and at 0.9 their colour smeared
          // through the wordmark.
          bgcolor: (theme) =>
            scrolled ? alpha(theme.palette.background.default, 0.94) : 'transparent',
          backdropFilter: scrolled ? 'blur(12px)' : 'none',
          transition: 'background-color 160ms ease, border-color 160ms ease',
        }}
      >
        {/* Same maxWidth as every prototype section, so the wordmark lines up
            with the hero copy underneath it. */}
        <Container
          maxWidth="lg"
          sx={{
            height: RESPONSIVE.landingProto.headerHeight,
            display: 'flex',
            alignItems: 'center',
            gap: RESPONSIVE.landingProto.headerGap,
          }}
        >
          <Link
            component={RouterLink}
            to={header.wordmark.to}
            underline="none"
            sx={{
              color: 'text.primary',
              fontWeight: 600,
              fontSize: RESPONSIVE.landingProto.headerWordmarkFontSize,
              letterSpacing: '-0.01em',
              whiteSpace: 'nowrap',
            }}
          >
            {header.wordmark.label}
          </Link>

          <Box
            component="nav"
            aria-label="Landing"
            sx={{ display: { xs: 'none', sm: 'flex' }, alignItems: 'center', gap: 3, ml: 2 }}
          >
            {header.nav.map((item) => (
              <Link
                key={item.label}
                component={RouterLink}
                to={item.to}
                variant="body2"
                underline="none"
                sx={{ color: 'text.secondary', '&:hover': { color: 'text.primary' } }}
              >
                {item.label}
              </Link>
            ))}
          </Box>

          {/* Pushes the auth cluster to the right edge of the container. */}
          <Box sx={{ flexGrow: 1 }} />

          <IconButton
            component="a"
            href={header.sourceCode.href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={header.sourceCode.label}
            size="small"
            sx={{
              display: { xs: 'none', sm: 'inline-flex' },
              color: 'text.secondary',
              '&:hover': { color: 'text.primary' },
            }}
          >
            {/* Desktop-only mark, so no mobile token: 20px reads as a peer of
                the body2 nav links beside it without becoming a third CTA. */}
            <GitHubIcon sx={{ fontSize: 20 }} />
          </IconButton>

          <Button
            component={RouterLink}
            to={header.logIn.to}
            variant="text"
            size="small"
            sx={{ display: { xs: 'none', sm: 'inline-flex' }, color: 'text.primary' }}
          >
            {header.logIn.label}
          </Button>

          <Button component={RouterLink} to={header.signUp.to} variant="contained" size="small">
            {header.signUp.label}
          </Button>
        </Container>
      </Box>
    </>
  );
}

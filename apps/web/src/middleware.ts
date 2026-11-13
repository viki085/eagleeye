import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// enterprise: no sign-up route; accounts are created by admins in the console
const isPublicRoute = createRouteMatcher(["/sign-in(.*)", "/status"]);

export default clerkMiddleware(async (auth, req) => {
  if (!isPublicRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};

export default function StalenessWarning({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl bg-orange-50 px-4 py-3 text-sm text-orange-800" role="alert">
      <svg className="mt-0.5 h-4 w-4 shrink-0 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <p>{message}</p>
    </div>
  );
}

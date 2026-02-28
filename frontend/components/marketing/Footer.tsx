export function Footer() {
  return (
    <footer id="contact" className="border-t px-6 py-8 md:px-12">
      <div className="mx-auto flex max-w-5xl items-center justify-between">
        <p className="text-sm text-gray-500">
          <span className="font-medium text-gray-700">Agent.ai</span> · Built for Indian
          enterprises
        </p>
        <p className="text-sm text-gray-400">© {new Date().getFullYear()}</p>
      </div>
    </footer>
  )
}

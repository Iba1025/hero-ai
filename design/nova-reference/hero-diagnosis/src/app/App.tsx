import { ArrowLeft, Volume2, MoreVertical, Camera, Send, Mic } from 'lucide-react';

export default function App() {
  return (
    <div className="h-screen w-full max-w-md mx-auto bg-[#F5C518] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-4 bg-[#F5C518]">
        <button className="p-2 -ml-2">
          <ArrowLeft className="w-6 h-6 text-black" />
        </button>
        <h1 className="font-semibold text-lg text-black">Hero Assistant</h1>
        <div className="flex items-center gap-2">
          <button className="p-2">
            <Volume2 className="w-6 h-6 text-black" />
          </button>
          <button className="p-2 -mr-2">
            <MoreVertical className="w-6 h-6 text-black" />
          </button>
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 px-4 py-6 overflow-y-auto">
        {/* Message Bubble */}
        <div className="flex items-start gap-3">
          {/* Avatar */}
          <div className="flex-shrink-0">
            <div className="w-10 h-10 rounded-full bg-white border-2 border-blue-500 flex items-center justify-center overflow-hidden">
              <div className="w-6 h-6 rounded-full bg-gradient-to-br from-blue-400 to-blue-600"></div>
            </div>
          </div>

          {/* Message */}
          <div className="flex flex-col">
            <div className="bg-[#2C2C2C] rounded-2xl rounded-tl-none px-4 py-3 max-w-[280px]">
              <p className="text-white text-sm leading-relaxed">
                Thank you for reaching out to Hero! I'm Nova, your home services booking assistant. What service do you need help with today — HVAC, plumbing, cleaning, or electrical?
              </p>
            </div>
            <span className="text-xs text-[#B8860B] mt-1 ml-2">6:57 PM</span>
          </div>
        </div>
      </div>

      {/* Input Area */}
      <div className="px-4 pb-6 pt-2 bg-[#F5C518]">
        <div className="flex items-center gap-3">
          {/* Camera Button */}
          <button className="flex-shrink-0 w-12 h-12 bg-white rounded-full flex items-center justify-center shadow-md">
            <Camera className="w-5 h-5 text-gray-700" />
          </button>

          {/* Text Input */}
          <div className="flex-1 bg-white rounded-full px-5 py-3 shadow-md">
            <input
              type="text"
              placeholder="Type or tap the mic to talk..."
              className="w-full bg-transparent border-none outline-none text-sm text-gray-700 placeholder-gray-400"
            />
          </div>

          {/* Send Button */}
          <button className="flex-shrink-0 w-12 h-12 bg-white rounded-full flex items-center justify-center shadow-md">
            <Send className="w-5 h-5 text-gray-400" />
          </button>

          {/* Mic Button */}
          <button className="flex-shrink-0 w-12 h-12 bg-black rounded-full flex items-center justify-center shadow-md">
            <Mic className="w-5 h-5 text-white" />
          </button>
        </div>

        {/* Tap to speak hint */}
        <div className="flex items-center justify-center gap-2 mt-3">
          <div className="w-2 h-2 bg-black rounded-full"></div>
          <span className="text-xs text-black">Tap to hold to speak</span>
        </div>
      </div>
    </div>
  );
}
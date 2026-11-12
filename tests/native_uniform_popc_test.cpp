#include <array>
#include <cstdio>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using Shader::Ampere::Instruction; using Shader::Ampere::LowerToMaxwell;
#define CHECK(x) do {if (!(x)) {std::printf("failed %d: %s\n",__LINE__,#x);return 1;}} while(0)
int main(){
 Instruction op{{0x000472bf,0x00000006,0x08000000,0}}, end{{0x0000794d,0,0x03800000,0}};
 std::array<Instruction,2> code{op,end}; auto r=LowerToMaxwell(code,"full",true);
 CHECK(r); CHECK(r.instructions.size()==2); CHECK((r.instructions[0]&0xff)==220); CHECK(((r.instructions[0]>>20)&255)==222); CHECK((r.instructions[0]&0xfff8000000000000ULL)==0x5c08000000000000ULL);
 code[0].words[0]=(code[0].words[0]&~0xf000u)|0x6000; CHECK(!LowerToMaxwell(code,"full",true));
 code[0]=op; code[0].words[1]=16; CHECK(!LowerToMaxwell(code,"full",true));
 code[0]=op; code[0].words[2]|=1; CHECK(!LowerToMaxwell(code,"full",true));
 std::puts("UPOPC register mapping and rejected modes passed");
}

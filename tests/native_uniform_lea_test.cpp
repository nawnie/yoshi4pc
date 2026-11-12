#include <array>
#include <cstdio>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using Shader::Ampere::Instruction; using Shader::Ampere::LowerToMaxwell;
#define CHECK(x) do { if (!(x)) {std::printf("failed line %d\n",__LINE__);return 1;} } while(0)
int main(){
 Instruction op{{0x00007c11,0x00000004,0x0f8e38ff,0}}, end{{0x0000794d,0,0x03800000,0}};
 std::array<Instruction,2> code{op,end}; auto r=LowerToMaxwell(code,"full");
 CHECK(r && r.instructions.size()==2); CHECK((r.instructions[0]&255)==0); CHECK(((r.instructions[0]>>8)&255)==0); CHECK(((r.instructions[0]>>20)&255)==220); CHECK(((r.instructions[0]>>39)&31)==7);
 code[0].words[1]=28; CHECK(!LowerToMaxwell(code,"full"));
 code[0]=op; code[0].words[2]^=1; CHECK(!LowerToMaxwell(code,"full"));
 std::puts("uniform LEA operand and mode checks passed");
}

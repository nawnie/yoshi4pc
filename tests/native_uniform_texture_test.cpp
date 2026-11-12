// Synthetic uniform-register TEX.SCR case: checks the diagnostic gate, operand fields and fail-closed modes.
#include <array>
#include <cstdint>
#include <cstdio>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using Shader::Ampere::Instruction;
using Shader::Ampere::LowerToMaxwell;
static void put(Instruction &i, unsigned bit, unsigned count, unsigned value) {
    for (unsigned n=0;n<count;n++) {
        const unsigned at=bit+n; const uint32_t mask=uint32_t(1)<<(at%32);
        i.words[at/32] = (i.words[at/32]&~mask) | ((value>>n&1) ? mask : 0);
    }
}
#define CHECK(x) do {if (!(x)) {std::fprintf(stderr,"failed line %d: %s\n",__LINE__,#x);return 1;}} while (0)
int main() {
    Instruction sample{}, exit{};
    put(sample,0,12,0xf60); put(sample,12,4,7); put(sample,16,8,12); put(sample,24,8,4);
    put(sample,32,8,5); put(sample,40,6,4); put(sample,60,1,1); put(sample,61,3,1);
    put(sample,64,8,14); put(sample,72,4,15); put(sample,81,3,7); put(sample,87,3,1); put(sample,91,1,1);
    put(exit,0,12,0x94d); put(exit,12,4,7); put(exit,87,4,7);
    std::array<Instruction,2> code{sample,exit};
    CHECK(!LowerToMaxwell(code,"full"));
    auto ok=LowerToMaxwell(code,"full",true);
    CHECK(ok && ok.instructions.size()==9);
    const uint64_t tex=ok.instructions[3];
    CHECK((tex & 0xffc0000000000000ULL)==0xde80000000000000ULL);
    CHECK(((tex>>8)&255)==250 && ((tex>>20)&255)==246 && ((tex>>28)&7)==2);
    CHECK(((tex>>31)&15)==15 && ((tex>>37)&7)==1);
    CHECK((ok.instructions[4]&255)==12 && (ok.instructions[5]&255)==13);
    CHECK((ok.instructions[6]&255)==14 && (ok.instructions[7]&255)==15);
    put(code[0],46,8,1); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],32,8,216); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],60,1,0); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],0,12,0xf63); put(code[0],87,3,2);
    CHECK(!LowerToMaxwell(code,"full"));
    auto gather=LowerToMaxwell(code,"full",true);
    CHECK(gather && gather.instructions.size()==9);
    CHECK((gather.instructions[3] & 0xffc0000000000000ULL)==0xdec0000000000000ULL);
    CHECK(((gather.instructions[3] >> 38) & 3)==2);
    put(code[0],76,2,1); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],91,1,0); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],72,4,1); put(code[0],16,8,11); put(code[0],64,8,255);
    auto scalar=LowerToMaxwell(code,"full",true);
    CHECK(scalar && scalar.instructions.size()==6 && (scalar.instructions[4]&255)==11);
    code[0]=sample; put(code[0],72,4,7); put(code[0],64,8,3);
    auto triple=LowerToMaxwell(code,"full",true);
    CHECK(triple && triple.instructions.size()==8 && (triple.instructions[6]&255)==3);
    code[0]=sample; put(code[0],72,4,1); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],0,12,0xf63); put(code[0],61,3,5); put(code[0],32,8,8); put(code[0],87,3,2);
    auto array_gather=LowerToMaxwell(code,"full",true);
    CHECK(array_gather && array_gather.instructions.size()==10);
    CHECK(((array_gather.instructions[0]>>20)&255)==4);
    CHECK(((array_gather.instructions[1]>>20)&255)==5);
    CHECK(((array_gather.instructions[2]>>20)&255)==8);
    CHECK(((array_gather.instructions[4]>>28)&7)==3);
    put(code[0],24,8,5); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],61,3,5); put(code[0],32,8,8);
    auto array_tex=LowerToMaxwell(code,"full",true);
    CHECK(array_tex && array_tex.instructions.size()==10);
    CHECK(((array_tex.instructions[1]>>20)&255)==5);
    CHECK(((array_tex.instructions[2]>>20)&255)==8);
    CHECK(((array_tex.instructions[4]>>28)&7)==3);
    put(code[0],24,8,5); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],87,3,0);
    auto implicit_lod=LowerToMaxwell(code,"full",true);
    CHECK(implicit_lod && implicit_lod.instructions.size()==9);
    CHECK(((implicit_lod.instructions[3]>>37)&7)==0);
    code[0]=sample; put(code[0],87,3,3); put(code[0],32,8,8);
    auto explicit_lod=LowerToMaxwell(code,"full",true);
    CHECK(explicit_lod && explicit_lod.instructions.size()==10);
    CHECK(((explicit_lod.instructions[0]>>20)&255)==4);
    CHECK(((explicit_lod.instructions[1]>>20)&255)==5);
    CHECK((explicit_lod.instructions[2]&255)==246);
    CHECK((explicit_lod.instructions[3]&255)==247 && ((explicit_lod.instructions[3]>>20)&255)==8);
    CHECK(((explicit_lod.instructions[4]>>37)&7)==3);
    put(code[0],24,8,5); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],61,3,5); put(code[0],87,3,3); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],61,3,2); put(code[0],32,8,8);
    auto volume_tex=LowerToMaxwell(code,"full",true);
    CHECK(volume_tex && volume_tex.instructions.size()==10);
    CHECK(((volume_tex.instructions[1]>>20)&255)==5);
    CHECK(((volume_tex.instructions[2]>>20)&255)==8);
    CHECK(((volume_tex.instructions[4]>>28)&7)==4);
    put(code[0],24,8,5); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],61,3,2); put(code[0],87,3,3); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],76,1,1); put(code[0],32,8,8);
    auto offset_tex=LowerToMaxwell(code,"full",true);
    CHECK(offset_tex && offset_tex.instructions.size()==10);
    CHECK(((offset_tex.instructions[0]>>20)&255)==4 && ((offset_tex.instructions[1]>>20)&255)==5);
    CHECK((offset_tex.instructions[3]&255)==247 && ((offset_tex.instructions[3]>>20)&255)==8);
    CHECK(((offset_tex.instructions[4]>>36)&1)==1 && ((offset_tex.instructions[4]>>37)&7)==1);
    put(code[0],24,8,5); CHECK(!LowerToMaxwell(code,"full",true));
    code[0]=sample; put(code[0],76,1,1); put(code[0],87,3,3); CHECK(!LowerToMaxwell(code,"full",true));
    std::puts("uniform texture lowering gate and operand checks passed");
}

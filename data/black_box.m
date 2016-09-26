function [transform] = black_box(magic, add, subtract, multiply, divide)
    transform = ((magic + add - subtract).*multiply)./divide;
end